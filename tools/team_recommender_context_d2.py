"""One deterministic context representation from trusted frozen public fields.

No source retrieval, profile enrichment, model selection or arbitrary packet text.
"""
import hashlib
import json
from collections import defaultdict

VERSION = "D2-context-v1"


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def context_inventory(settings):
    """Return exact allowed inputs, preserving associated active claim ownership."""
    inventory = {}
    for person, claims in sorted(settings["profile_claims"].items()):
        fields = settings["d1_profile_fields"][person]
        by_id = {c["id"]: c for c in fields["claims"]}
        by_text = defaultdict(list)
        for claim in claims:
            metadata = by_id[claim["claim_id"]]
            # Revisions/evidence belong to the trusted profile_claims table;
            # D1's separately hash-bound context table contains labels/types.
            by_text[claim["text"]].append({"claim_type": metadata["claim_type"], "label": metadata["label"]})
        texts = []
        for evidence, associated in sorted(by_text.items()):
            unique = sorted({canonical(c) for c in associated})
            texts.append(canonical({"evidence": evidence, "claims": [json.loads(c) for c in unique]}))
        if fields["research_summary"]:
            texts.append(canonical({"research_summary": fields["research_summary"]}))
        inventory[person] = {hashlib.sha256(t.encode("utf-8")).hexdigest(): t for t in texts}
    return inventory
