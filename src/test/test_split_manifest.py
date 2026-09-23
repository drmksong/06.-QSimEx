import unittest

from src.core.split_manifest import split_cases_by_domain, build_manifest


class TestSplitManifest(unittest.TestCase):
    def make_cases(self):
        # Create 10 domains with varying case counts
        cases = []
        for i in range(10):
            dom = f"D{i}"
            for j in range(i + 1):
                cases.append({"id": f"{dom}-{j}", "domain": dom})
        return cases

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


if __name__ == "__main__":
    unittest.main()
