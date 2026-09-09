"""Immutable, content-addressed Funding Finder candidates and exact-byte receipts.

No source or provider calls are made here. Only the generation job creates data;
assembly, validation, materialization and publication use durable artifacts.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import yaml

ROOT = Path(__file__).resolve().parents[1]
POLICY = "config/release_dependencies.json"
VERSION = "immutable-release-1"
MANIFEST = "candidate.json"
GATES = ("package-integrity", "python", "browser", "frozen-query", "scoring", "no-drift", "notice-projection")


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_bytes())


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded(value))


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def checked_path(root, name):
    parts = PurePosixPath(name)
    if not name or "\\" in name or parts.is_absolute() or any(p in ("..", ".git") for p in parts.parts) or ":" in name:
        raise ValueError(f"Unsafe candidate path: {name}")
    path = Path(root) / name
    if path.is_symlink() or not path.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError(f"Candidate path escapes its root: {name}")
    return path


def paths(root, patterns):
    result = set()
    for pattern in patterns:
        matches = [p for p in Path(root).glob(pattern) if p.is_file()]
        if not matches and not any(c in pattern for c in "*?["):
            raise ValueError(f"Required release input is missing: {pattern}")
        for path in matches:
            name = path.relative_to(root).as_posix()
            if "__pycache__" not in path.parts:
                checked_path(root, name)
                result.add(name)
    return sorted(result)


def file_hashes(root, names):
    return {name: digest(checked_path(root, name).read_bytes()) for name in sorted(names)}


def worker_fingerprint(root, policy, inputs_root=None):
    inputs_root = inputs_root or root
    hashes = file_hashes(inputs_root, paths(inputs_root, policy['worker']))
    if 'worker_toolchain' in policy:
        workflow = (Path(root) / '.github/workflows/refresh-opportunities.yml').read_text(encoding='utf-8')
        versions = set(re.findall(r'npx --yes wrangler@([0-9.]+) deploy', workflow))
        if versions != {policy['worker_toolchain']['wrangler']}:
            raise ValueError('Worker deployment toolchain differs from its declared fingerprint')
        hashes['@toolchain'] = digest(encoded(policy['worker_toolchain']))
    return digest(encoded(hashes))


def generation_dependencies(root):
    policy = read_json(Path(root) / POLICY)
    names = set(paths(root, policy["generation"])) - set(policy["generation_excluded"])
    hashes = {}
    for name in sorted(names):
        content = (Path(root) / name).read_bytes()
        if name.endswith(".py"):
            # Comments/docstrings are not generation semantics.
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
                    first = node.body[0]
                    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                        node.body.pop(0)
            content = ast.dump(tree, include_attributes=False).encode()
        hashes[name] = digest(content)
    invocations = []
    workflow = Path(root) / '.github/workflows/refresh-opportunities.yml'
    if workflow.exists():
        for step in yaml.safe_load(workflow.read_text(encoding='utf-8'))['jobs']['generate']['steps']:
            command = step.get('run', '')
            if re.search(r'python -m scripts\.|node tools/build_search_v2_voyage_vectors\.mjs', command):
                # Hash generation command/arguments and safe input configuration,
                # not orchestration, diagnostics, cache keys or secret values.
                environment = {k: v for k, v in step.get('env', {}).items() if 'secrets.' not in str(v)}
                invocations.append({'command': ' '.join(command.split()), 'environment': environment})
    return {"fingerprint": digest(encoded([hashes, policy["generation_contract"], invocations])),
            "files": hashes, "contract": policy["generation_contract"], 'invocations': invocations}


def declared_versions(root, names):
    versions = {}
    for name in names:
        if not name.endswith('.py'):
            continue
        values = {}
        for node in ast.parse((Path(root) / name).read_bytes()).body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and re.search(r'(?:VERSION|MODEL|EMBEDDING_CONFIG)$', target.id):
                        try:
                            values[target.id] = ast.literal_eval(node.value)
                        except (ValueError, TypeError):
                            pass
        if values:
            versions[name] = values
    return versions


def privacy_check(path):
    # Only explicit, existing public-derived inputs enter a bundle. Never glob
    # caches, runner temp, evaluation inboxes, private structures or raw notices.
    if path.suffix == ".json":
        forbidden = {"raw_text", "full_text", "email_body", "raw_email", "api_key", "access_token", "private_key"}
        def inspect(value):
            if isinstance(value, dict):
                if forbidden.intersection(k.lower() for k in value):
                    raise ValueError(f"Private material is forbidden in candidate input {path.name}")
                for child in value.values():
                    inspect(child)
            elif isinstance(value, list):
                for child in value:
                    inspect(child)
        inspect(read_json(path))


def create(root, output, *, generation_sha=None, run_id=None, attempt=None, parent=None, team_update=False):
    root, output = Path(root), Path(output)
    if output.exists():
        raise ValueError("Candidate destination already exists; immutable artifacts cannot be overwritten")
    policy = read_json(root / POLICY)
    generation = generation_dependencies(root)
    if parent:
        original = load(parent)
        verify_dependencies(root, original, allowed=('teams',) if team_update else ())
        retained = {n: h for n, h in original['generation_files'].items() if not team_update or n not in policy['team_outputs']}
        verify_files(root, retained)
    else:
        original = None
    names = paths(root, policy["generated"] + policy["package"] + policy["runtime"])
    files = file_hashes(root, names)
    generated_names = paths(root, policy["generated"])
    generation_files = [n for n in generated_names if n not in ('README.md', 'PROJECT.md', '.github/last_build')]
    # Documentation/heartbeat are retained byte-for-byte but do not seed parsing.
    seeds = [n for n in generated_names if n.startswith(("data/", "config/"))]
    sha = generation_sha or git(root, "rev-parse", "HEAD")
    if not re.fullmatch(r"[a-f0-9]{40}", sha):
        raise ValueError("Generation provenance requires a complete commit SHA")
    baseline = {}
    for name in seeds:
        baseline[name] = digest(subprocess.check_output(["git", "-C", str(root), "show", f"{sha}:{name}"]))
    runtime_baseline = {}
    for name in paths(root, policy['runtime']):
        runtime_baseline[name] = digest(subprocess.check_output(['git', '-C', str(root), 'show', f'{sha}:{name}']))
    semantic = read_json(root / "data/search-v2-voyage-manifest.json")
    team = read_json(root / "config/opportunity_team_model.json")
    release = read_json(root / "data/search-v2-release.json")
    manifest = {"schema_version": 1, "candidate_format": VERSION,
                "generation_sha": sha, "generation_run_id": str(run_id or os.environ["GITHUB_RUN_ID"]),
                "generation_run_attempt": str(attempt or os.environ.get("GITHUB_RUN_ATTEMPT", "1")),
                "generation_timestamp": timestamp(), "generation_dependencies": generation,
                "generator_versions": declared_versions(root, generation['files']),
                "generation_baseline": baseline, "generation_files": {n: files[n] for n in generation_files},
                "runtime_baseline": runtime_baseline,
                "files": files, "worker_fingerprint": worker_fingerprint(root, policy),
                "semantic_identity": {k: semantic.get(k) for k in ("schema_version", "model", "response_model", "dimension", "input_type", "source_output_dtype", "model_space_fingerprint", "corpus_sha256")},
                "team_identity": {"generation_id": team.get("generation_id"), "input_sha256": files["config/opportunity_team_model.json"]},
                "release_identity": {k: release.get(k) for k in ("current_corpus_sha256", "previous_corpus_sha256", "model_space_fingerprint", "worker_allowlist_sha256")}}
    from tools.release_dependencies import snapshot
    if 'dependency_groups' in policy:
        manifest['dependency_groups'] = snapshot(root)
    if original:
        for key in ("generation_sha", "generation_run_id", "generation_run_attempt", "generation_timestamp", "generation_dependencies", "generator_versions", "generation_baseline", "generation_files", "team_identity", "semantic_identity"):
            if not team_update or key not in ('generation_baseline', 'generation_files', 'team_identity'):
                manifest[key] = original[key]
        manifest["derived_from_candidate"] = original["candidate_id"]
        manifest["assembly_sha"] = git(root, "rev-parse", "HEAD")
        if team_update:
            manifest['team_generation'] = {'sha': sha, 'run_id': str(run_id or os.environ['GITHUB_RUN_ID']),
                'run_attempt': str(attempt or os.environ.get('GITHUB_RUN_ATTEMPT', '1')),
                'timestamp': timestamp(), 'parent_candidate_id': original['candidate_id'],
                'pinned_inputs': original['generation_files'], 'retained_output_hashes': retained,
                'provider_contract': read_json(root / 'config/offline_ai.json')}
    manifest["candidate_id"] = digest(encoded(manifest))
    for name in names:
        privacy_check(root / name)
        target = checked_path(output / "files", name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    write_json(output / MANIFEST, manifest)
    return load(output)


def verify_files(root, hashes):
    for name, expected in hashes.items():
        path = checked_path(root, name)
        if not path.is_file() or digest(path.read_bytes()) != expected:
            raise ValueError(f"Candidate bytes differ: {name}")


def load(bundle, expected_id=None):
    bundle = Path(bundle)
    value = read_json(bundle / MANIFEST)
    identity = value.get("candidate_id")
    if identity != digest(encoded({k: v for k, v in value.items() if k != "candidate_id"})) or (expected_id and expected_id != identity):
        raise ValueError("Candidate manifest identity mismatch")
    if value.get("schema_version") != 1 or value.get("candidate_format") != VERSION:
        raise ValueError("Unsupported candidate manifest")
    verify_files(bundle / "files", value["files"])
    actual = {p.relative_to(bundle / "files").as_posix() for p in (bundle / "files").rglob("*") if p.is_file()}
    if actual != set(value["files"]):
        raise ValueError("Unmanifested candidate files")
    return value


def verify_dependencies(root, manifest, allowed=()):
    if not re.fullmatch(r'[a-f0-9]{40}', manifest.get('generation_sha', '')):
        raise ValueError('Invalid historical generation provenance')
    if subprocess.run(['git', '-C', str(root), 'merge-base', '--is-ancestor', manifest['generation_sha'], 'HEAD'],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
        raise ValueError('Generation SHA is not in the protected release history')
    policy = read_json(Path(root) / POLICY)
    current = generation_dependencies(root)
    if 'dependency_groups' in policy:
        from tools.release_dependencies import verify
        verify(root, manifest, allowed)
    elif current != manifest["generation_dependencies"]:
        changed = sorted(k for k in set(current["files"]) | set(manifest["generation_dependencies"]["files"])
                         if current["files"].get(k) != manifest["generation_dependencies"]["files"].get(k))
        raise ValueError(f"Generation dependencies changed; request one new generation: {changed}")
    for name, baseline in manifest["generation_baseline"].items():
        if 'teams' in allowed and name in policy.get('team_outputs', []):
            continue
        actual = digest(checked_path(root, name).read_bytes())
        if actual not in (baseline, manifest["files"][name]):
            raise ValueError(f"Generation data input changed: {name}; candidate invalidated")
    return current["fingerprint"]


def materialize(root, bundle):
    manifest = load(bundle)
    verify_dependencies(root, manifest)
    if set(paths(root, read_json(Path(root) / POLICY)['runtime'])) != set(manifest['runtime_baseline']):
        raise ValueError('Release runtime inventory changed; assemble a reuse candidate without generation')
    for name, baseline in manifest['runtime_baseline'].items():
        if digest(checked_path(root, name).read_bytes()) not in (baseline, manifest['files'][name]):
            raise ValueError(f'Release runtime changed: {name}; assemble a reuse candidate without generation')
    for name in manifest["files"]:
        if name in ('README.md', 'PROJECT.md') and digest(checked_path(root, name).read_bytes()) != manifest['files'][name]:
            raise ValueError('Authored documentation changed; assemble a derived candidate preserving current prose: ' + name)
        target = checked_path(root, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(bundle) / "files" / name, target)
    verify_files(root, manifest["files"])
    return manifest


def validation_identity(root, manifest):
    policy = read_json(Path(root) / POLICY)
    files = file_hashes(root, paths(root, policy["validation"] + policy["generation"]))
    # Gate data and frozen reference frames are validation dependencies too.
    files.update(file_hashes(root, paths(root, ['evaluation/*.json', 'evaluation/*.txt', 'tools/*.sh'])))
    for name in manifest['files']:
        files.pop(name, None)
    return {"version": VERSION, "fingerprint": digest(encoded(files)), "files": files,
            "candidate_id": manifest["candidate_id"], "candidate_hashes": manifest["files"]}


def final_integration_identity(root, manifest):
    """Bind browser tests, fixtures, and their relative repository imports."""
    root = Path(root).resolve()
    names = set(paths(root, ['tests/e2e/**/*', 'tests/fixtures/**/*',
                            'playwright.config.*', 'package.json', 'pnpm-lock.yaml']))
    pending = list(names)
    while pending:
        name = pending.pop()
        if Path(name).suffix not in ('.js', '.mjs', '.cjs'):
            continue
        source = checked_path(root, name)
        for relative in re.findall(r'''\b(?:from\s*|import\s*(?:\(\s*)?)["'](\.{1,2}/[^"']+)["']''', source.read_text(encoding='utf-8')):
            target = (source.parent / relative).resolve()
            if not target.is_relative_to(root):
                raise ValueError('Browser test import escapes repository')
            dependency = target.relative_to(root).as_posix()
            if dependency not in names:
                names.add(dependency)
                pending.append(dependency)
    return {'candidate_id': manifest['candidate_id'], 'candidate_hashes': manifest['files'],
            'test_inputs': file_hashes(root, names)}


def verify_receipt(root, bundle, receipt, *, require_final=True):
    manifest = load(bundle)
    verify_dependencies(root, manifest)
    if worker_fingerprint(root, read_json(Path(root) / POLICY), Path(bundle) / 'files') != manifest['worker_fingerprint']:
        raise ValueError('Candidate Worker compatibility inputs changed; assemble a reuse candidate')
    if receipt.get("identity") != validation_identity(root, manifest) or receipt.get("generation_sha") != manifest["generation_sha"]:
        raise ValueError("Validation receipt does not cover current validators and exact candidate")
    if receipt.get("gates") != {name: "passed" for name in GATES}:
        raise ValueError("Validation receipt lacks required passing gates")
    if require_final and 'final_integration' in receipt:
        final = receipt['final_integration']
        if (not isinstance(final, dict) or final.get('passed') is not True
                or final.get('identity') != final_integration_identity(root, manifest)):
            raise ValueError('Required final browser integration is incomplete or stale; resume manual validation')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["create", "verify", "materialize", "dependencies", "receipt"])
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--candidate-id")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--parent", type=Path)
    parser.add_argument('--team-update', action='store_true')
    args = parser.parse_args()
    if args.command == "create":
        manifest = create(args.root, args.bundle, parent=args.parent, team_update=args.team_update)
    else:
        manifest = load(args.bundle, args.candidate_id)
        if args.command == "materialize":
            materialize(args.root, args.bundle)
        elif args.command == "dependencies":
            verify_dependencies(args.root, manifest)
        elif args.command == "receipt":
            verify_receipt(args.root, args.bundle, read_json(args.receipt))
    print(json.dumps({"candidate_id": manifest["candidate_id"], "generation_sha": manifest["generation_sha"]}))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            output.write(f"candidate_id={manifest['candidate_id']}\n")


if __name__ == "__main__":
    main()
