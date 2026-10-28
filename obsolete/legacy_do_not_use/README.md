# LEGACY_DO_NOT_USE

This directory documents provisional analysis code retained for audit history.
It must not be used to generate research results.

The following paths contain the retired single-threshold or 4.0-based logic:

- `multi_case_descision.py`
- `trial/try.py`
- `tools/inspect_likelihoods.py`
- `tools/inspect_likelihoods_counts.py`
- `tools/analyze_partial_lowfract_run.py`

The active reporting path now refuses to emit provisional binary-classification
results. These files will be removed after the explicit lower/upper cutoff
pipeline is connected and validated.