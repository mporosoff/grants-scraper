"""Five explicit release dependency groups, including historical Git inputs.

Historical fingerprints are recomputed under the current policy, never relabeled
as new generation. Missing historical files differ from newly introduced inputs.
"""
import ast
import io
import json
import re
from pathlib import Path
import subprocess
import tarfile
import yaml

from tools import release_candidate as c


def semantic_bytes(name, content):
    if name.endswith('.py'):
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                    node.body.pop(0)
        return ast.dump(tree, include_attributes=False).encode()
    return content


def matches(name, pattern):
    expression = re.escape(pattern).replace(r'\*\*/', '(?:.*/)?').replace(r'\*\*', '.*').replace(r'\*', '[^/]*').replace(r'\?', '[^/]')
    return re.fullmatch(expression, name) is not None


def snapshot(root, revision=None):
    policy = c.read_json(Path(root) / c.POLICY)
    if revision:
        archive = tarfile.open(fileobj=io.BytesIO(subprocess.check_output(['git', '-C', str(root), 'archive', revision])))
        inventory = [item.name for item in archive if item.isfile()]
        def read(name):
            return archive.extractfile(name).read()
    else:
        inventory = c.git(root, 'ls-files', '--cached', '--others', '--exclude-standard').splitlines()
        def read(name):
            return c.checked_path(root, name).read_bytes()
    generated = policy['generated'] + policy['package']
    result = {}
    workflow = yaml.safe_load(read('.github/workflows/refresh-opportunities.yml'))
    recorded_policy = json.loads(read(c.POLICY)) if revision else policy
    invocations = {'source': [], 'semantic': []}
    team_commands = ('scripts.build_opportunity_teams', 'scripts.faculty_match')
    for step in workflow['jobs']['generate']['steps']:
        command = step.get('run', '')
        # The budget wrapper invokes this exact unchanged module/arguments.
        # Provider routing and parser semantics remain fingerprinted separately.
        command = command.replace('python -m tools.run_budgeted_documents', 'python -m scripts.extract_document_evidence')
        if any(part in command for part in team_commands):
            continue
        group = ('semantic' if 'node tools/build_search_v2_voyage_vectors.mjs' in command else
                 'source' if re.search(r'python -m scripts\.', command) else None)
        if group:
            environment = {k: v for k, v in step.get('env', {}).items() if 'secrets.' not in str(v)
                           and k not in ('OFFLINE_AI_STATE', 'TEAM_MODE')}
            invocations[group].append({'command': ' '.join(command.split()), 'environment': environment})
    for group, rule in policy['dependency_groups'].items():
        selected = [name for name in inventory if not any(matches(name, p) for p in generated) and name not in rule['excluded']
                    and any(matches(name, pattern) for pattern in rule['patterns'])]
        files = {name: c.digest(semantic_bytes(name, read(name))) for name in sorted(set(selected))}
        if group in invocations:
            files['@generation_invocations'] = c.digest(c.encoded(invocations[group]))
            runtime_key = 'python' if group == 'source' else 'node'
            files['@generator_runtime'] = c.digest(c.encoded(recorded_policy.get('generation_contract', {}).get(runtime_key)))
        result[group] = {'files': files, 'fingerprint': c.digest(c.encoded(files))}
    return result


def candidate_groups(root, manifest):
    if 'dependency_groups' in manifest:
        return manifest['dependency_groups']
    # An old manifest's original protected generation remains the reference for
    # source/team/semantic inputs. Runtime and validators may have advanced later.
    groups = snapshot(root, manifest['generation_sha'])
    runtime = snapshot(root, manifest.get('assembly_sha', manifest['generation_sha']))
    groups['runtime'] = runtime['runtime']
    return groups


def changed_groups(before, after):
    return {group: sorted(name for name in set(before[group]['files']) | set(after[group]['files'])
                         if before[group]['files'].get(name) != after[group]['files'].get(name))
            for group in before if before[group] != after[group]}


def verify(root, manifest, allowed=()):
    before, current = candidate_groups(root, manifest), snapshot(root)
    changes = changed_groups(before, current)
    blocked = {group: files for group, files in changes.items() if group in ('source', 'teams', 'semantic') and group not in allowed}
    if blocked:
        raise ValueError('Candidate dependency mismatch; required action ' +
                         ('generate' if set(blocked) - {'teams'} else 'teams') + ': ' + json.dumps(blocked, sort_keys=True))
    return current
