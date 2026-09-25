import json
import tempfile
import unittest
from pathlib import Path

from src.core.coverage_rounds import (
    append_ledger,
    build_round_record,
    coverage_delta,
    deduplicate_domain_records,
)


class TestCoverageRounds(unittest.TestCase):
    def _audit(self, minimum, maximum, statuses):
        return {
            "observed_min": minimum,
            "observed_max": maximum,
            "bins": [
                {"bin_index": index, "status": status}
                for index, status in enumerate(statuses)
            ],
        }

    def test_coverage_delta_tracks_new_and_remaining_gaps(self):
        before = self._audit(5.0, 40.0, ["observed", "UNOBSERVED", "UNOBSERVED"])
        after = self._audit(2.0, 80.0, ["observed", "observed", "UNOBSERVED"])

        delta = coverage_delta(before, after)

        self.assertEqual(delta["observed_qprime_range_after"], [2.0, 80.0])
        self.assertEqual(delta["newly_observed_bins"], [1])
        self.assertEqual(delta["remaining_gap_bins"], [2])
        self.assertEqual(delta["unobserved_bin_delta"], -1)

    def test_deduplicates_domain_and_signature_pairs(self):
        result = deduplicate_domain_records(
            [
                {"domain_id": "D1", "generation_signature_hash": "S1"},
                {"domain_id": "D1", "generation_signature_hash": "S1"},
                {"domain_id": "D1", "generation_signature_hash": "S2"},
            ]
        )

        self.assertEqual(result["n_unique"], 2)
        self.assertEqual(result["n_duplicates"], 1)
        self.assertEqual(result["duplicate_domain_ids"], ["D1"])

    def test_round_record_and_jsonl_ledger(self):
        before = self._audit(5.0, 40.0, ["observed", "UNOBSERVED"])
        after = self._audit(2.0, 80.0, ["observed", "observed"])
        record = build_round_record(
            round_id=1,
            run_id="r001",
            round_type="coverage_expansion",
            before_audit=before,
            after_audit=after,
            n_domains=10,
            n_signatures=3,
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.jsonl"
            append_ledger(str(path), record)
            saved = json.loads(path.read_text(encoding="utf-8").strip())

        self.assertEqual(saved["round_id"], 1)
        self.assertEqual(saved["newly_observed_bins"], [1])


if __name__ == "__main__":
    unittest.main()
