"""Exercise official identity through the supported catalog/cache integration route."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.sources.merge import integrate, load_catalog, rebuild_catalog, save_catalog, _resolve_identity_before_selection
from tests.test_vpr_window_retention import DAY, cache, observed, row


URL = "https://simpler.grants.gov/opportunity/12345678-1234-1234-1234-123456789abc"
TARGET = "https://www.grants.gov/search-results-detail/123456"


def proof(target=TARGET):
    return {"version": 1, "source_url": URL, "target_url": target,
        "utf8_sha256": "a" * 64, "retrieved_at": "2026-09-23T12:00:00Z",
        "locator": "View on Grants.gov / version-history anchor"}


def aliases():
    a = row("same", detail_page=URL, funding_opportunity_url=URL)
    return a, dict(a, detail_page=TARGET, funding_opportunity_url=TARGET)


class Client:
    def __init__(self):
        self.calls = []
        self.html = '<a href="' + TARGET + '">View on Grants.gov</a>'
        self.error = None

    def get_text(self, url):
        self.calls.append(url)
        self.last_url = url
        if self.error:
            raise self.error
        return self.html


class OfficialIdentityIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.catalog = self.root / "catalog.js"
        self.snapshot = self.root / "source-cache.json"
        self.client = Client()

    def seed(self, state, records=()):
        save_catalog(rebuild_catalog({"generated_at": "2026-09-23T12:00:00Z"}, list(records), [], []), self.catalog)
        self.snapshot.write_text(json.dumps(state), encoding="utf8")

    def run_window(self, result, enabled=True):
        with patch.dict(os.environ, {"VPR_ENRICH_LINKS": "true" if enabled else "false"}), \
                patch("scripts.sources.merge.collect", return_value=([], [copy.deepcopy(result)])), \
                patch("scripts.sources.http.PoliteClient", return_value=self.client):
            summary = integrate(self.catalog, self.snapshot, as_of=DAY, write=True)
        return summary, load_catalog(self.catalog), json.loads(self.snapshot.read_bytes())

    def test_cached_and_first_fetched_aliases_precede_selection_and_canonical_merge(self):
        for cached in (True, False):
            self.client.calls.clear()
            a, b = aliases()
            state = cache(); state["official_identities"] = {URL: proof()} if cached else {}
            canonical = dict(b, opportunity_id="123456", source="Grants.gov", description="Canonical official scope")
            self.seed(state, [canonical])
            summary, catalog, saved = self.run_window(observed(b, a))
            self.assertEqual(len(self.client.calls), 0 if cached else 1)
            self.assertEqual(summary["sources"][0]["identity_collision_ids"], [])
            self.assertEqual(len(catalog["opportunities"]), 1)
            actual = catalog["opportunities"][0]
            self.assertEqual((actual["opportunity_id"], actual["description"]), ("123456", "Canonical official scope"))
            self.assertEqual(saved["sources"]["vpr-email"]["records"][0]["official_identity"]["target_url"], TARGET)
            self.assertEqual(saved["official_identities"][URL]["target_url"], TARGET)

    def test_witness_only_history_can_recover_with_cached_or_fetched_exact_proof(self):
        for cached in (True, False):
            self.client.calls.clear()
            a, b = aliases(); self.seed(cache())
            _, catalog, saved = self.run_window(observed(a, b), enabled=False)
            self.assertEqual(catalog["opportunities"], [])
            original = copy.deepcopy(saved["sources"]["vpr-email"]["identity_witnesses"]["observations"])
            if cached:
                saved["official_identities"] = {URL: proof()}
                self.snapshot.write_text(json.dumps(saved), encoding="utf8")
            summary, catalog, saved = self.run_window(observed(b), enabled=not cached)
            self.assertEqual(len(catalog["opportunities"]), 1)
            self.assertEqual(len(self.client.calls), 0 if cached else 1)
            self.assertEqual(summary["sources"][0]["identity_collision_ids"], [])
            witnesses = saved["sources"]["vpr-email"]["identity_witnesses"]["observations"]
            self.assertTrue(all(w in witnesses for w in original))
            self.assertEqual(len(witnesses), 3)
            _, _, again = self.run_window(observed(b), enabled=False)
            self.assertEqual(again["sources"]["vpr-email"]["identity_witnesses"]["observations"], witnesses)

    def test_flag_off_and_invalid_or_contradictory_proof_do_not_guess_aliases(self):
        for receipt in (None, dict(proof(), locator="unverified"), proof(TARGET.replace("123456", "654321"))):
            state = cache(); state["official_identities"] = {URL: receipt} if receipt else {}
            self.seed(state)
            summary, catalog, saved = self.run_window(observed(*aliases()), enabled=False)
            self.assertEqual(self.client.calls, [])
            self.assertEqual(catalog["opportunities"], [])
            self.assertEqual(summary["sources"][0]["identity_collision_ids"], ["vpr-email:same"])
            self.assertEqual(summary["sources"][0]["observed_terminal_records"], [])

    def test_one_shared_twenty_get_bound_covers_fresh_retained_and_witness_proxies(self):
        items = []
        for i in range(21):
            url = f"https://simpler.grants.gov/opportunity/12345678-1234-1234-1234-{i:012x}"
            items.append(row(str(i), detail_page=url, funding_opportunity_url=url))
        self.seed(cache(*items))
        summary, _, _ = self.run_window(observed(*items))
        self.assertEqual(len(self.client.calls), 20)
        self.assertEqual(len(set(self.client.calls)), 20)
        self.assertEqual(summary["official_identity_resolution"]["attempted"], 20)

    def test_failed_untrusted_observations_never_enter_identity_lookup(self):
        self.seed(cache())
        failed = observed(*aliases()); failed.ok = False; failed.error = "parser failed"
        summary, catalog, saved = self.run_window(failed)
        self.assertEqual(self.client.calls, [])
        self.assertEqual(catalog["opportunities"], [])
        self.assertFalse(summary["sources"][0]["healthy"])
        self.assertEqual(saved["sources"]["vpr-email"]["identity_witnesses"]["observations"], [])

    def test_verified_partial_partition_and_failed_cached_fallback_keep_old_refresh_identity(self):
        a, _ = aliases()
        state = cache(a); state["official_identities"] = {URL: proof()}
        self.seed(state)
        failed = observed(); failed.ok = False
        summary, catalog, saved = self.run_window(failed)
        self.assertEqual(len(catalog["opportunities"]), 1)
        self.assertEqual(saved["sources"]["vpr-email"]["fetched_at"], state["sources"]["vpr-email"]["fetched_at"])
        self.assertEqual(self.client.calls, [])
        fresh = dict(a, opportunity_id="vpr-email:part-new")
        partial = observed(fresh, diagnostics={"partial_failure": True, "partitions": [
            {"id_prefix": "vpr-email:part-", "healthy": True, "status": "refreshed"}]})
        partial.ok = False
        summary, _, saved = self.run_window(partial)
        self.assertEqual(summary["sources"][0]["status"], "partial_refresh")
        self.assertFalse(summary["sources"][0]["healthy"])
        self.assertEqual(saved["sources"]["vpr-email"]["last_successful_refresh_at"], "2026-09-07T12:00:00Z")

    def test_resolution_failure_leaves_complete_catalog_and_cache_unchanged(self):
        self.seed(cache())
        before = [p.read_bytes() for p in (self.catalog, self.snapshot)]
        self.client.error = ValueError("official source unavailable")
        with self.assertRaisesRegex(ValueError, "official source unavailable"):
            self.run_window(observed(*aliases()))
        self.assertEqual([p.read_bytes() for p in (self.catalog, self.snapshot)], before)
        self.assertEqual(len(self.client.calls), 1)

    def test_retained_recipe_explicitly_forbids_fetch_even_when_workflow_flag_is_on(self):
        state = cache(); state["official_identities"] = {URL: proof()}
        with patch.dict(os.environ, {"VPR_ENRICH_LINKS": "true"}), \
                patch("scripts.sources.http.PoliteClient", side_effect=AssertionError("No source request allowed")):
            stats = _resolve_identity_before_selection([observed(*aliases())], state, DAY, allow_fetch=False)
            self.assertEqual(stats["attempted"], 0)
            self.assertGreater(stats["reused"], 0)


if __name__ == "__main__":
    unittest.main()
