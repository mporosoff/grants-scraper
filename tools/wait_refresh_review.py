"""Bounded read-only checkpoint for an explicitly requested manual release run.

The release operator reviews/tests the immutable generated PR and merges through
protection. This helper never requests reviews, changes checks, or merges a PR.
"""
import argparse
import json
import re
import subprocess
import time


def read_pull_request(url):
    result = subprocess.run(
        ["gh", "pr", "view", url, "--json", "headRefOid,baseRefName,baseRefOid,state,mergeCommit"],
        check=True, capture_output=True, text=True, timeout=30,
    )
    return json.loads(result.stdout)


def read_merged_commit(url, sha):
    repository = "/".join(url.split("/")[3:5])
    result = subprocess.run(["gh", "api", f"repos/{repository}/git/commits/{sha}"],
                            check=True, capture_output=True, text=True, timeout=30)
    return json.loads(result.stdout)


def wait_for_merge(url, head_sha, base_sha, tree_sha, *, timeout=1800, interval=15,
                   read=read_pull_request, read_commit=read_merged_commit,
                   now=time.monotonic, sleep=time.sleep):
    if not re.fullmatch(r"https://github\.com/[^/]+/[^/]+/pull/[1-9][0-9]*", url):
        raise ValueError("Invalid generated pull request URL")
    if any(not re.fullmatch(r"[a-f0-9]{40}", value) for value in (head_sha, base_sha, tree_sha)):
        raise ValueError("Invalid generated candidate, base or tree SHA")
    deadline = now() + timeout
    consecutive_errors = 0
    while now() < deadline:
        try:
            state = read(url)
            commit = None
            if isinstance(state, dict) and state.get("state") == "MERGED":
                merge_ref = state.get("mergeCommit")
                merge_sha = merge_ref.get("oid") if isinstance(merge_ref, dict) else None
                if isinstance(merge_sha, str) and re.fullmatch(r"[a-f0-9]{40}", merge_sha):
                    commit = read_commit(url, merge_sha)
        except (subprocess.SubprocessError, OSError, ValueError):
            consecutive_errors += 1
            if consecutive_errors >= 3:
                raise RuntimeError("Generated PR state unavailable after bounded retries") from None
        else:
            consecutive_errors = 0
            if not isinstance(state, dict) or state.get("headRefOid") != head_sha:
                raise RuntimeError("Generated candidate changed during manual validation")
            if state.get("baseRefName") != "main" or state.get("baseRefOid") != base_sha:
                raise RuntimeError("Protected base changed during manual validation")
            if state.get("state") == "MERGED":
                merge_commit = state.get("mergeCommit")
                merged = merge_commit.get("oid") if isinstance(merge_commit, dict) else None
                if not isinstance(merged, str) or not re.fullmatch(r"[a-f0-9]{40}", merged):
                    raise RuntimeError("Missing protected merge identity")
                parents = commit.get("parents") if isinstance(commit, dict) else None
                tree = commit.get("tree") if isinstance(commit, dict) else None
                if (not isinstance(parents, list) or not parents or not isinstance(parents[0], dict)
                        or parents[0].get("sha") != base_sha or not isinstance(tree, dict)
                        or tree.get("sha") != tree_sha or commit.get("sha") != merged):
                    raise RuntimeError("Protected merge does not preserve the validated base and tree")
                return merged
            if state.get("state") != "OPEN":
                raise RuntimeError("Generated PR closed without a protected merge")
        sleep(min(interval, max(0, deadline - now())))
    raise RuntimeError("Manual generated-package validation window expired")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pr_url")
    parser.add_argument("head_sha")
    parser.add_argument("base_sha")
    parser.add_argument("tree_sha")
    args = parser.parse_args()
    print(f"Awaiting manual validation and protected merge of {args.pr_url} at {args.head_sha}", flush=True)
    print(wait_for_merge(args.pr_url, args.head_sha, args.base_sha, args.tree_sha))


if __name__ == "__main__":
    main()
