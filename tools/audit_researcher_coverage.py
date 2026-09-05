"""Report source-backed researcher coverage without inventing scientific claims."""
import json
from collections import Counter
from pathlib import Path

from scripts.researcher_registry import load_registry, registry_counts


def audit(registry):
    rows = []
    for person in registry["researchers"]:
        claims = [claim for claim in person["claims"] if claim["status"] == "active"]
        rows.append({
            "researcher_id": person["researcher_id"], "name": person["display_name"],
            "active_claim_count": len(claims), "official_interest_count": len(person.get("official_interests", [])),
            "source_checked_date": person["source_checked_date"], "source_urls": person["source_urls"],
            "all_claims_have_evidence_and_sources": all(claim["evidence"] and claim["source_urls"] for claim in claims),
            "coverage_followup": "no retained claim" if not claims else "single retained capability" if len(claims) == 1 else "",
        })
    return {"registry_generation": registry["registry_generation"], "counts": registry_counts(registry),
        "active_claim_distribution": dict(sorted(Counter(row["active_claim_count"] for row in rows).items())),
        "rows": rows,
        "interpretation": "Few claims identify profiles to inspect; they do not prove missing expertise. Existing evidence phrases can improve retrieval immediately. Add scientific claims only from verified sources or approved profile updates."}


if __name__ == "__main__":
    report = audit(load_registry())
    target = Path("evaluation/researcher_coverage_audit.json")
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"researchers": len(report["rows"]), "claim_distribution": report["active_claim_distribution"]}))
