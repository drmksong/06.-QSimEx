import unittest

from src.core.split_manifest import (
    split_cases_by_domain,
    build_manifest,
    generation_signature,
    build_domain_signature_map,
    domain_signature_hash,
    assert_unique_domain_signatures,
    build_domain_record,
    validate_domain_split,
)


class TestSplitManifest(unittest.TestCase):
    def make_cases(self):
        # Create 10 domains with varying case counts
        cases = []
        for i in range(10):
            dom = f"D{i}"
            for j in range(i + 1):
                cases.append({"id": f"{dom}-{j}", "domain": dom})
        return cases

    def make_feature_cases(self):
        return [
            build_domain_record(
                "D0",
                seed=42,
                joint_sets=[
                    {"set_id": 1, "mean_dip": 45.0, "mean_dip_dir": 90.0, "fisher_kappa": 20.0,
                     "size_alpha": 3.0, "size_r_min": 0.5, "size_r_max": 10.0, "density_type": "P32",
                     "P32": 1.0, "mean_spacing": 0.5},
                ],
                global_params={"Jw_mean": 0.66, "SRF_mean": 2.5},
            ),
            build_domain_record(
                "D1",
                seed=43,
                joint_sets=[
                    {"set_id": 1, "mean_dip": 60.0, "mean_dip_dir": 150.0, "fisher_kappa": 30.0,
                     "size_alpha": 3.5, "size_r_min": 0.7, "size_r_max": 12.0, "density_type": "P32",
                     "P32": 1.5, "mean_spacing": 0.8},
                ],
                global_params={"Jw_mean": 0.9, "SRF_mean": 3.0},
            ),
            build_domain_record(
                "D2",
                seed=44,
                joint_sets=[
                    {"set_id": 1, "mean_dip": 75.0, "mean_dip_dir": 200.0, "fisher_kappa": 25.0,
                     "size_alpha": 4.0, "size_r_min": 0.9, "size_r_max": 14.0, "density_type": "P32",
                     "P32": 2.0, "mean_spacing": 1.0},
                ],
                global_params={"Jw_mean": 1.0, "SRF_mean": 3.5},
            ),
        ]

    def test_split_preserves_domain(self):
        cases = self.make_cases()
        train, val = split_cases_by_domain(cases, domain_key="domain", train_frac=0.7, random_state=1)

        # ensure no domain appears in both
        train_domains = {c["domain"] for c in train}
        val_domains = {c["domain"] for c in val}
        self.assertTrue(train_domains.isdisjoint(val_domains))

    def test_build_manifest(self):
        cases = self.make_cases()
        m = build_manifest(cases)
        self.assertEqual(m["n_cases"], len(cases))
        self.assertIn("D0", m["domains"])

    def test_generation_signatures_are_unique_and_feature_based(self):
        cases = self.make_feature_cases()
        sig_map = build_domain_signature_map(cases, domain_key="domain")
        self.assertEqual(len(sig_map), 3)

        hashes = [domain_signature_hash(sig) for sig in sig_map.values()]
        self.assertEqual(len(hashes), len(set(hashes)))
        self.assertEqual(generation_signature(cases[0]), sig_map["D0"])

    def test_assert_unique_domain_signatures(self):
        cases = self.make_feature_cases()
        assert_unique_domain_signatures(cases, domain_key="domain")

    def test_validate_domain_split(self):
        cases = self.make_feature_cases()
        summary = validate_domain_split(cases, domain_key="domain", train_frac=0.67, random_state=1)
        self.assertIn("n_train", summary)
        self.assertIn("n_validation", summary)
        self.assertEqual(summary["domain_overlap"], [])


if __name__ == "__main__":
    unittest.main()
