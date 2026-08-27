"""Command line for the multi-source layer.

Examples
--------
List every known adapter and whether it is enabled::

    python -m scripts.sources list

Preview what adapters would contribute, WITHOUT touching the catalog::

    python -m scripts.sources dry-run
    python -m scripts.sources dry-run --adapter sample --include-disabled

Merge enabled adapters into the catalog (the drop-in pipeline step)::

    python -m scripts.sources merge                 # preview only (no write)
    python -m scripts.sources merge --write         # actually rewrite the file
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .merge import DEFAULT_CACHE, DEFAULT_CATALOG, integrate
from .registry import REGISTRY, collect


def summary_is_degraded(summary: dict, *, write_requested: bool = False) -> bool:
    """Return True when an enabled source or post-merge validation degraded."""
    if not (summary.get("validation") or {}).get("ok"):
        return True
    if write_requested and summary.get("written") is False:
        return True
    return any(
        source.get("status") not in {"refreshed", "recent_snapshot"}
        for source in summary.get("sources") or []
    )


def _select(adapter_slug):
    if not adapter_slug:
        return None
    chosen = [a for a in REGISTRY if a.slug == adapter_slug]
    if not chosen:
        raise SystemExit(f"No adapter with slug {adapter_slug!r}. "
                         f"Known: {', '.join(a.slug for a in REGISTRY)}")
    return chosen


def cmd_list(_args):
    if not REGISTRY:
        print("No adapters registered.")
        return
    width = max(len(a.slug) for a in REGISTRY)
    print(f"{'SLUG'.ljust(width)}  ENABLED  TYPE        SOURCE")
    for a in REGISTRY:
        print(f"{a.slug.ljust(width)}  "
              f"{'yes' if a.enabled else 'no ':<7}  "
              f"{a.source_type:<10}  {a.display_name}")


def cmd_dry_run(args):
    adapters = _select(args.adapter)
    records, results = collect(adapters=adapters, include_disabled=args.include_disabled)
    for r in results:
        status = "ok" if r.ok else f"ERROR ({r.error})"
        print(f"- {r.display_name} [{r.slug}]: {r.record_count} records  {status}")
    print(f"\nTotal external records: {len(records)}")
    for record in records[:args.sample]:
        print(f"  * {record['title'][:80]}  "
              f"(source={record['source']}, close={record.get('close_date')})")
    if not results:
        print("Nothing ran. Enable an adapter or pass --include-disabled.")


def cmd_merge(args):
    adapters = _select(args.adapter)
    summary = integrate(
        catalog_path=Path(args.catalog),
        cache_path=Path(args.cache),
        adapters=adapters,
        include_disabled=args.include_disabled,
        write=args.write,
    )
    if args.summary_output:
        summary_path = Path(args.summary_output)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(summary, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(summary, indent=2))
    if not args.write:
        print("\n(Preview only. Re-run with --write to update the catalog file.)")
    if args.fail_on_degraded and summary_is_degraded(
        summary, write_requested=args.write
    ):
        print(
            "\nOne or more enabled sources or the merged catalog degraded. "
            "Healthy records and permitted filtered snapshots were retained; "
            "fail-closed sources published zero."
        )
        raise SystemExit(2)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m scripts.sources")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list registered adapters").set_defaults(func=cmd_list)

    dry = sub.add_parser("dry-run", help="preview adapter output; no file writes")
    dry.add_argument("--adapter", help="only run this adapter slug")
    dry.add_argument("--include-disabled", action="store_true",
                     help="also run adapters that are not yet enabled")
    dry.add_argument("--sample", type=int, default=5, help="sample rows to print")
    dry.set_defaults(func=cmd_dry_run)

    merge = sub.add_parser("merge", help="merge enabled adapters into the catalog")
    merge.add_argument("--catalog", default=str(DEFAULT_CATALOG),
                       help="path to the generated opportunities.js")
    merge.add_argument("--cache", default=str(DEFAULT_CACHE),
                       help="path to the source snapshot cache (last-known-good)")
    merge.add_argument("--adapter", help="only run this adapter slug")
    merge.add_argument("--include-disabled", action="store_true")
    merge.add_argument("--write", action="store_true",
                       help="actually rewrite the catalog (default is preview)")
    merge.add_argument(
        "--fail-on-degraded",
        action="store_true",
        help=(
            "exit nonzero after safe write/fallback when an enabled source "
            "or post-merge validation is degraded"
        ),
    )
    merge.add_argument(
        "--summary-output",
        help="write the structured refresh summary to this operational path",
    )
    merge.set_defaults(func=cmd_merge)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
