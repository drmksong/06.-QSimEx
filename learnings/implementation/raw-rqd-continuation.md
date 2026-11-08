# Raw-RQD Continuation

QSimEx raw-RQD follow-up batches resume from persisted review pauses while preserving prior measurements.

## What Happened

In QSimEx task `70dd5c0c-ca4d-44c0-a6b9-de931c9a34e9`, continuation from `initial_cohort_review` was implemented and exercised on baseline3. The first follow-up added 10 signatures per Jn, paused for review, and all 900 saved BH observations matched values independently recomputed from intersection evidence.

## Takeaway

Keep the original run/config/runtime fingerprint unchanged when resuming a persisted run. Release only recognized review-pause reasons, preserve completed attempts, generate unique bounded candidates, and pause after each batch. The current batch ratio is fixed at 5 global LHS plus 5 response-gap candidates per Jn; response-gap locations adapt to saved coverage, but changing the ratio requires an explicit policy decision. Real database execution remains separately approval-gated.

## History

- 2026-11-08 (`QSimEx/70dd5c0c-ca4d-44c0-a6b9-de931c9a34e9`): initial
