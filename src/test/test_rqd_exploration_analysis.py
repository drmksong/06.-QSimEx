from __future__ import annotations

from dataclasses import replace
from math import nextafter
import unittest
from unittest.mock import patch

from src.rqd_exploration import analysis
from src.rqd_exploration.config import JA_VALUES, JR_VALUES
from src.rqd_exploration.fingerprint import fingerprint_snapshot


class TestScenarioScoring(unittest.TestCase):
    def test_all_66_scenarios_keep_raw_rqd_separate_from_calculation_floor(self) -> None:
        scores = analysis.calculate_scenario_scores(0.0, 1.0)

        self.assertEqual(len(scores), 66)
        self.assertEqual(
            [(score.jr_value, score.ja_value) for score in scores],
            [(jr, ja) for jr in JR_VALUES for ja in JA_VALUES],
        )
        self.assertTrue(all(score.raw_rqd == 0.0 for score in scores))
        self.assertTrue(all(score.calculation_rqd == 10.0 for score in scores))
        self.assertEqual(scores[1].qprime, 5.0)

    def test_raw_rqd_ten_and_one_hundred_are_not_floored_or_rounded(self) -> None:
        at_ten = analysis.calculate_scenario_scores(10.0, 1.0)[1]
        at_one_hundred = analysis.calculate_scenario_scores(100.0, 1.0)[1]

        self.assertEqual((at_ten.raw_rqd, at_ten.calculation_rqd), (10.0, 10.0))
        self.assertEqual((at_one_hundred.raw_rqd, at_one_hundred.calculation_rqd),
                         (100.0, 100.0))
        self.assertEqual(at_ten.qprime, 5.0)
        self.assertEqual(at_one_hundred.qprime, 50.0)

    def test_zero_cross_is_recorded_without_forcing_a_scenario(self) -> None:
        scores = analysis.calculate_scenario_scores(10.0, 1.0, zero_cross=True)

        self.assertEqual(len(scores), 66)
        self.assertTrue(all(score.zero_cross for score in scores))
        self.assertEqual(scores[0].jr_value, JR_VALUES[0])
        self.assertEqual(scores[0].ja_value, JA_VALUES[0])

    def test_invalid_inputs_are_rejected(self) -> None:
        for value in (-0.1, 100.1, float("nan"), float("inf")):
            with self.subTest(raw_rqd=value), self.assertRaises(ValueError):
                analysis.calculate_scenario_scores(value, 1.0)
        with self.assertRaises(TypeError):
            analysis.calculate_scenario_scores(True, 1.0)
        with self.assertRaises(ValueError):
            analysis.calculate_scenario_scores(10.0, 1.5)
        with self.assertRaises(TypeError):
            analysis.calculate_scenario_scores(10.0, 1.0, zero_cross=1)  # type: ignore[arg-type]

    def test_selected_jr_ja_axes_are_canonical_and_change_analysis_fingerprint(self) -> None:
        scores = analysis.calculate_scenario_scores(
            80.0,
            2.0,
            jr_values=(2.0, 0.5),
            ja_values=(4.0, 1.0),
        )
        self.assertEqual(
            [(score.jr_value, score.ja_value) for score in scores],
            [(jr, ja) for jr in (0.5, 2.0) for ja in (1.0, 4.0)],
        )

        full = analysis.build_cumulative_analysis_snapshot(1, "a" * 64)
        selected = analysis.build_cumulative_analysis_snapshot(
            1,
            "a" * 64,
            jr_values=(2.0, 0.5),
            ja_values=(4.0, 1.0),
        )
        reordered = analysis.build_cumulative_analysis_snapshot(
            1,
            "a" * 64,
            jr_values=(0.5, 2.0),
            ja_values=(1.0, 4.0),
        )
        changed = analysis.build_cumulative_analysis_snapshot(
            1,
            "a" * 64,
            jr_values=(1.0,),
            ja_values=(1.0,),
        )
        self.assertEqual(selected, reordered)
        self.assertNotEqual(selected, full)
        self.assertNotEqual(
            fingerprint_snapshot(selected).sha256_hex,
            fingerprint_snapshot(changed).sha256_hex,
        )

    def test_selected_jr_ja_values_must_be_nonempty_unique_catalog_subsets(self) -> None:
        for kwargs in (
            {"jr_values": ()},
            {"jr_values": (1.25,)},
            {"ja_values": (1.0, 1.0)},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                analysis.calculate_scenario_scores(80.0, 2.0, **kwargs)


class TestScenarioBins(unittest.TestCase):
    def test_exact_edges_use_lower_exclusive_upper_inclusive_bins(self) -> None:
        self.assertEqual(len(analysis.BIN_EDGES), 11)
        for upper_edge_index, edge in enumerate(analysis.BIN_EDGES[1:], start=1):
            with self.subTest(edge=edge):
                self.assertEqual(analysis.assign_qprime_bin(edge), str(upper_edge_index))

    def test_400_is_in_primary_bin_and_only_values_above_it_overflow(self) -> None:
        self.assertEqual(analysis.assign_qprime_bin(400.0), "10")
        self.assertEqual(analysis.assign_qprime_bin(nextafter(400.0, float("inf"))),
                         analysis.OVERFLOW_BIN_ID)

    def test_nonpositive_or_nonfinite_qprime_is_rejected(self) -> None:
        for value in (0.0, -1.0, float("nan"), float("inf")):
            with self.subTest(qprime=value), self.assertRaises(ValueError):
                analysis.assign_qprime_bin(value)
        with self.assertRaises(TypeError):
            analysis.assign_qprime_bin(True)


class TestReferenceProfileAnalysis(unittest.TestCase):
    def _observation(
        self,
        *,
        modality: str,
        profile_id: str,
        location_index: int,
        raw_rqd: float,
        valid: bool = True,
        support: float = 1.0,
        p32: tuple[tuple[str, float], ...] = (),
    ) -> analysis.AnalysisObservation:
        return analysis.AnalysisObservation(
            manifest_id="manifest",
            design_id="design",
            block_id="block",
            sample_index=0,
            realization_seed=17,
            execution_fingerprint_digest="a" * 64,
            modality=modality,  # type: ignore[arg-type]
            profile_id=profile_id,
            location_index=location_index,
            raw_rqd=raw_rqd,
            fixed_jn=1.0,
            is_valid=valid,
            exclusion_reason=None if valid else "no valid support",
            zero_cross=False,
            support_length_m=support if modality == "BH" else None,
            support_area_m2=support if modality == "face" else None,
            p32_by_joint_set=p32,
        )

    def _status(
        self,
        observation: analysis.AnalysisObservation,
    ) -> analysis.AnalysisLocationStatus:
        return analysis.AnalysisLocationStatus(
            manifest_id=observation.manifest_id,
            design_id=observation.design_id,
            block_id=observation.block_id,
            sample_index=observation.sample_index,
            realization_seed=observation.realization_seed,
            execution_fingerprint_digest=observation.execution_fingerprint_digest,
            modality=observation.modality,
            profile_id=observation.profile_id,
            location_index=observation.location_index,
            status="observed",
            reason=None,
        )

    def test_summarizes_scenarios_support_and_nonpaired_profile_contrasts(self) -> None:
        bh = self._observation(
            modality="BH",
            profile_id="bh-main",
            location_index=0,
            raw_rqd=80.0,
            support=4.0,
            p32=(("joint-set-1", 2.5),),
        )
        face = self._observation(
            modality="face",
            profile_id="tunnel-face",
            location_index=0,
            raw_rqd=30.0,
            support=8.0,
        )
        result = analysis.analyze_reference_profiles(
            (bh, face),
            (self._status(bh), self._status(face)),
        )

        self.assertEqual(result.source_observation_count, 2)
        self.assertEqual(result.scenario_evaluation_count, 132)
        self.assertEqual(len(result.scenario_summaries), 132)
        bh_summary = next(
            item for item in result.scenario_summaries
            if item.modality == "BH" and item.jr_value == 1.0 and item.ja_value == 1.0
        )
        face_summary = next(
            item for item in result.scenario_summaries
            if item.modality == "face" and item.jr_value == 1.0 and item.ja_value == 1.0
        )
        self.assertEqual((bh_summary.support_unit, bh_summary.total_support), ("m", 4.0))
        self.assertEqual((face_summary.support_unit, face_summary.total_support), ("m2", 8.0))
        self.assertEqual(bh_summary.weighted_median_qprime, 80.0)
        self.assertEqual(face_summary.weighted_median_qprime, 30.0)
        self.assertEqual(bh_summary.signature_count, 1)
        self.assertEqual(bh_summary.realization_count, 1)
        self.assertAlmostEqual(sum(
            item.support_fraction for item in bh_summary.bin_support
        ), 1.0)

        contrast = next(
            item for item in result.distribution_contrasts
            if item.jr_value == 1.0 and item.ja_value == 1.0
        )
        self.assertEqual(contrast.face_minus_bh_weighted_median_qprime, -50.0)
        self.assertEqual((contrast.bh_support_m, contrast.face_support_m2), (4.0, 8.0))
        self.assertEqual(contrast.comparability_status, "comparable")
        self.assertEqual(len(contrast.bin_fraction_differences), 11)
        self.assertEqual(len(result.qprime_p32_points), 66)

    def test_invalid_and_zero_support_observations_are_counted_but_not_weighted(self) -> None:
        invalid = self._observation(
            modality="BH",
            profile_id="bh-main",
            location_index=0,
            raw_rqd=10.0,
            valid=False,
            support=2.0,
        )
        zero_support = self._observation(
            modality="BH",
            profile_id="bh-main",
            location_index=1,
            raw_rqd=20.0,
            support=0.0,
        )
        result = analysis.analyze_reference_profiles(
            (invalid, zero_support),
            (self._status(invalid), self._status(zero_support)),
        )

        summary = result.scenario_summaries[0]
        self.assertEqual(summary.observation_count, 2)
        self.assertEqual(summary.valid_support_observation_count, 0)
        self.assertEqual(summary.total_support, 0.0)
        self.assertIsNone(summary.weighted_median_qprime)
        self.assertEqual(summary.minimum_qprime, None)
        status = result.location_status_summaries[0]
        self.assertEqual(status.observed_count, 2)
        self.assertEqual(status.invalid_observation_count, 1)
        self.assertEqual(status.zero_support_observation_count, 1)

    def test_location_statuses_preserve_missing_and_unavailable_reasons(self) -> None:
        missing = analysis.AnalysisLocationStatus(
            "manifest", "design", "block", 0, 17, "a" * 64,
            "BH", "bh-main", 0, "missing", "observation not persisted",
        )
        unavailable = analysis.AnalysisLocationStatus(
            "manifest", "design", "block", 0, 17, "a" * 64,
            "BH", "bh-main", 1, "unavailable", "outside valid boundary",
        )
        planned = analysis.AnalysisLocationStatus(
            "manifest", "design", "block", 0, 17, "a" * 64,
            "BH", "bh-main", 2, "planned", None,
        )
        result = analysis.analyze_reference_profiles((), (missing, unavailable, planned))

        status = result.location_status_summaries[0]
        self.assertEqual(
            (
                status.planned_count,
                status.observed_count,
                status.unavailable_count,
                status.missing_count,
            ),
            (1, 0, 1, 1),
        )
        self.assertEqual(
            {(item.status, item.reason, item.count)
             for item in result.location_status_reason_counts},
            {
                ("missing", "observation not persisted", 1),
                ("unavailable", "outside valid boundary", 1),
            },
        )

    def test_weighted_median_uses_physical_support_not_observation_count(self) -> None:
        first = self._observation(
            modality="BH",
            profile_id="bh-main",
            location_index=0,
            raw_rqd=20.0,
            support=3.0,
        )
        second = replace(
            self._observation(
                modality="BH",
                profile_id="bh-main",
                location_index=0,
                raw_rqd=80.0,
                support=1.0,
            ),
            design_id="design-2",
        )
        result = analysis.analyze_reference_profiles(
            (first, second),
            (self._status(first), self._status(second)),
        )

        summary = next(
            item for item in result.scenario_summaries
            if item.jr_value == 1.0 and item.ja_value == 1.0
        )
        self.assertEqual(summary.weighted_median_qprime, 20.0)
        self.assertEqual(summary.total_support, 4.0)
        self.assertEqual(summary.signature_count, 2)
        self.assertEqual(summary.realization_count, 2)

    def test_observed_statuses_must_match_raw_observations(self) -> None:
        observation = self._observation(
            modality="BH",
            profile_id="bh-main",
            location_index=0,
            raw_rqd=50.0,
        )
        with self.assertRaises(ValueError):
            analysis.analyze_reference_profiles((), (self._status(observation),))

    def test_p32_values_must_be_consistent_across_bh_locations_in_a_job(self) -> None:
        first = self._observation(
            modality="BH",
            profile_id="bh-main",
            location_index=0,
            raw_rqd=50.0,
            p32=(("joint-set-1", 2.5),),
        )
        second = replace(first, location_index=1, p32_by_joint_set=())
        with self.assertRaisesRegex(ValueError, "same P32 values"):
            analysis.analyze_reference_profiles(
                (first, second),
                (self._status(first), self._status(second)),
            )

    def test_face_observations_reject_bh_only_p32_values(self) -> None:
        face = self._observation(
            modality="face",
            profile_id="tunnel-face",
            location_index=0,
            raw_rqd=50.0,
            p32=(("joint-set-1", 2.5),),
        )
        with self.assertRaisesRegex(ValueError, "only for BH"):
            analysis.analyze_reference_profiles((face,), (self._status(face),))

    def test_unavailable_profiles_are_reported_instead_of_silent_empty_outputs(self) -> None:
        result = analysis.analyze_reference_profiles((), ())
        unavailable_ids = {item.profile_id for item in result.unavailable_profiles}

        self.assertIn("detection_miss_ratio", unavailable_ids)
        self.assertIn("face_areal_density", unavailable_ids)
        self.assertIn("tunnel_axis_intersection_rate", unavailable_ids)
        self.assertIn("retry_count", unavailable_ids)
        self.assertIn("qprime_bh_p32", unavailable_ids)
        self.assertIn("bh_face_distribution_contrast", unavailable_ids)
        self.assertFalse(result.retry_count_available)


class TestAnalysisFingerprints(unittest.TestCase):
    def test_raw_dataset_fingerprint_is_canonical_and_tracks_raw_content(self) -> None:
        first = {
            "schema_version": 1,
            "observations": [{"raw_rqd": 12.5, "modality": "BH"}],
        }
        reordered = {
            "observations": [{"modality": "BH", "raw_rqd": 12.5}],
            "schema_version": 1,
        }
        changed = {
            "schema_version": 1,
            "observations": [{"raw_rqd": 12.6, "modality": "BH"}],
        }

        self.assertEqual(
            analysis.fingerprint_raw_dataset(first).sha256_hex,
            analysis.fingerprint_raw_dataset(reordered).sha256_hex,
        )
        self.assertNotEqual(
            analysis.fingerprint_raw_dataset(first).sha256_hex,
            analysis.fingerprint_raw_dataset(changed).sha256_hex,
        )
        self.assertEqual(first["observations"][0]["raw_rqd"], 12.5)

    def test_analysis_fingerprint_tracks_dataset_and_analysis_rules_separately(self) -> None:
        dataset = {"schema_version": 1, "observations": [{"raw_rqd": 10.0}]}
        changed_dataset = {
            "schema_version": 1,
            "observations": [{"raw_rqd": 11.0}],
        }
        raw_digest = analysis.fingerprint_raw_dataset(dataset).sha256_hex
        changed_raw_digest = analysis.fingerprint_raw_dataset(
            changed_dataset,
        ).sha256_hex

        baseline = analysis.fingerprint_analysis(1, raw_digest).sha256_hex
        changed_data_analysis = analysis.fingerprint_analysis(
            1, changed_raw_digest,
        ).sha256_hex
        with patch.object(analysis, "CALCULATION_RQD_FLOOR", 11.0):
            changed_rule_analysis = analysis.fingerprint_analysis(
                1, raw_digest,
            ).sha256_hex
        with patch.object(analysis, "JN_VALUES", (0.5, 1.0)):
            changed_jn_analysis = analysis.fingerprint_analysis(
                1, raw_digest,
            ).sha256_hex

        self.assertNotEqual(raw_digest, changed_raw_digest)
        self.assertNotEqual(baseline, changed_data_analysis)
        self.assertNotEqual(baseline, changed_rule_analysis)
        self.assertNotEqual(baseline, changed_jn_analysis)
        self.assertEqual(
            analysis.fingerprint_raw_dataset(dataset).sha256_hex,
            raw_digest,
        )

    def test_analysis_fingerprint_validates_dataset_reference(self) -> None:
        with self.assertRaises(ValueError):
            analysis.fingerprint_raw_dataset({"schema_version": 2})
        with self.assertRaises(ValueError):
            analysis.build_analysis_snapshot(0, "0" * 64)
        with self.assertRaises(ValueError):
            analysis.build_analysis_snapshot(1, "A" * 64)
        with self.assertRaises(ValueError):
            analysis.build_analysis_snapshot(1, "0" * 63)


if __name__ == "__main__":
    unittest.main()
