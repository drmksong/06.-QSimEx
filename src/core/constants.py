"""Standard nomenclature and helpers for decision-analysis metrics.

Purpose:
- Provide a single source-of-truth for mixed FP/FN/cost naming seen in the
  codebase and specification.
- Offer a small utility to normalize legacy metric dictionaries to canonical
  keys used in reports and selectors.

This module is intentionally small and dependency-free so it can be imported
from tests and other modules without side effects.
"""
from typing import Dict, Any

# Canonical keys used across reporting and selection logic
CANONICAL = {
    "FP": "FP_false_safe",
    "FN": "FN_false_alarm",
    "TP": "TP_correct_excavate",
    "TN": "TN_correct_reject",
    "N": "n",
    "ACTUAL_GOOD": "actual_good",
    "ACTUAL_BAD": "actual_bad",
    "PRED_GOOD": "pred_good",
    "PRED_BAD": "pred_bad",
    "EXPECTED_COST": "expected_cost",
    "NET_BENEFIT": "net_benefit",
}

# Common cost-related keys in the codebase
STANDARD_COST_KEYS = {
    "cost_fp": "cost_fp",
    "cost_fn": "cost_fn",
    "cost_false_safe": "cost_false_safe",
    "cost_false_alarm": "cost_false_alarm",
}

# Legacy/alternate names observed in the repo mapped to canonical names
LEGACY_TO_CANONICAL = {
    "FP_false_safe": CANONICAL["FP"],
    "false_safe_rate": "false_safe_rate",
    "false_alarm_rate": "false_alarm_rate",
    "FN_false_alarm": CANONICAL["FN"],
    "false_alarm": CANONICAL["FN"],
    "FP": CANONICAL["FP"],
    "FN": CANONICAL["FN"],
    "TP": CANONICAL["TP"],
    "TN": CANONICAL["TN"],
    "n": CANONICAL["N"],
    "expected_cost": CANONICAL["EXPECTED_COST"],
    "net_benefit": CANONICAL["NET_BENEFIT"],
    "R_FS_pass": "R_FS_pass",
    "R_FN_reject": "R_FN_reject",
    # cost keys
    "cost_fp": STANDARD_COST_KEYS["cost_fp"],
    "cost_fn": STANDARD_COST_KEYS["cost_fn"],
    "cost_safe": "cost_false_safe",
    "cost_alarm": "cost_false_alarm",
    # other legacy cost namings seen in repo
    "cost_false_safe": STANDARD_COST_KEYS["cost_false_safe"],
    "cost_false_alarm": STANDARD_COST_KEYS["cost_false_alarm"],
}


def standardize_metrics(metrics: Dict[str, Any], copy: bool = True) -> Dict[str, Any]:
    """Return a new dict with legacy keys replaced by canonical keys.

    - If `copy` is True (default) the input dict is not mutated.
    - Keys not recognized are preserved.
    """
    if metrics is None:
        return {}

    out = dict(metrics) if copy else metrics

    for legacy, canon in LEGACY_TO_CANONICAL.items():
        if legacy in metrics and canon not in out:
            out[canon] = metrics[legacy]

    # Ensure canonical keys for a few core counts if present as alternate forms
    # e.g. accept both 'FP_false_safe' and 'FP' as sources
    for k in ["FP_false_safe", "FN_false_alarm", "TP_correct_excavate", "TN_correct_reject"]:
        if k in metrics:
            # map to canonical if possible
            if k in LEGACY_TO_CANONICAL and LEGACY_TO_CANONICAL[k] not in out:
                out[LEGACY_TO_CANONICAL[k]] = metrics[k]

    return out


__all__ = ["CANONICAL", "STANDARD_COST_KEYS", "LEGACY_TO_CANONICAL", "standardize_metrics"]
