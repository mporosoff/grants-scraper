"""Adapter registry and error-isolated collection.

Adapters register themselves at import time. ``collect`` runs the enabled
adapters and, critically, isolates failures: one broken source can never abort
the merge or poison the catalog -- it is reported and skipped, and the last
good catalog is preserved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .base import SourceAdapter

#: All adapters known to the layer (enabled or not).
REGISTRY: list[SourceAdapter] = []


def register(adapter: SourceAdapter) -> SourceAdapter:
    """Register an adapter instance. Returns it so it can be used inline."""
    if not isinstance(adapter, SourceAdapter):
        raise TypeError("register() expects a SourceAdapter instance")
    if any(existing.slug == adapter.slug for existing in REGISTRY):
        raise ValueError(f"Duplicate adapter slug: {adapter.slug!r}")
    REGISTRY.append(adapter)
    return adapter


@dataclass
class AdapterResult:
    slug: str
    display_name: str
    source_type: str
    ok: bool
    record_count: int = 0
    error: Optional[str] = None
    records: list = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)
    min_records: Optional[int] = None
    max_records: Optional[int] = None
    fallback_grace_days: int = 0


def collect(adapters: Optional[list[SourceAdapter]] = None,
            include_disabled: bool = False) -> tuple[list[dict], list[AdapterResult]]:
    """Run adapters and return ``(records, per_adapter_results)``.

    - ``adapters`` defaults to the global REGISTRY.
    - Disabled adapters are skipped unless ``include_disabled`` is True.
    - Any adapter that raises is captured in its result with ``ok=False``; its
      records are omitted but every other adapter still contributes.
    """
    pool = REGISTRY if adapters is None else adapters
    all_records: list[dict] = []
    results: list[AdapterResult] = []
    for adapter in pool:
        if not adapter.enabled and not include_disabled:
            continue
        try:
            records = adapter.collect()
        except Exception as exc:  # noqa: BLE001 - deliberate per-source isolation
            results.append(
                AdapterResult(
                    slug=adapter.slug,
                    display_name=adapter.display_name,
                    source_type=adapter.source_type,
                    ok=False,
                    error=f"{type(exc).__name__}: {exc}",
                    diagnostics=dict(getattr(adapter, "diagnostics", {}) or {}),
                    min_records=adapter.min_records,
                    max_records=adapter.max_records,
                    fallback_grace_days=adapter.fallback_grace_days,
                )
            )
            continue
        results.append(
            AdapterResult(
                slug=adapter.slug,
                display_name=adapter.display_name,
                source_type=adapter.source_type,
                ok=True,
                record_count=len(records),
                records=records,
                diagnostics=dict(getattr(adapter, "diagnostics", {}) or {}),
                min_records=adapter.min_records,
                max_records=adapter.max_records,
                fallback_grace_days=adapter.fallback_grace_days,
            )
        )
        all_records.extend(records)
    return all_records, results
