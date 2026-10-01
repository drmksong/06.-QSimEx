# Stage 4 signature-update handoff (2026-10-01)

## Purpose

This document records the implemented Stage 4 boundary, the small real smoke
result, and the remaining work needed before a large campaign. Continue from
this document instead of inferring state from old campaign directories.

## Implemented

- `validation/run_campaign.py` has a non-dry-run strategy-catalog executor.
- Approved D/A/B/C candidates run one at a time with an inclusive common seed
  range. A/B/C candidates change exactly one feature.
- Results are accumulated with domain/signature deduplication and primary
  10-bin plus auxiliary 20-bin audits.
- Atomic `campaign_checkpoint.json` and `ledger.jsonl` snapshots support resume.
  A valid completed CSV is reused by phase, canonical generation signature, and
  complete seed set; failed or incomplete attempts use a new attempt directory.
- A response candidate is generated only from a qualifying same-seed observed
  `delta_x/delta_C`. Catalog candidates and response candidates alternate, so a
  P32 response chain cannot starve B/C screening.
- E is a separate fixed-signature repeatability phase using only explicit
  `--repeatability-seed` values. E rows do not contribute to coverage.
- `coverage_complete` and `profile_cutoff_identified` are independent states.
  Bounds exhaustion, no direction, candidate exhaustion, and iteration limits
  preserve remaining gaps instead of reporting completion.
- Default outer iteration ceiling is 4000.

## Active reviewed catalog

File: `validation/highq_strategy_catalog.yml`

All entries use the same canonical parent generation signature and absolute
primary target bin 8. The planner now honors explicit
`validity_constraints.target_bins` even when the bin's relative gap class
changes as the observed range moves.

| Family | Feature                     |            Probe | Reviewed bounds |
| ------ | --------------------------- | ---------------: | --------------: |
| A      | `joint_sets.0.P32`          |         10 -> 20 | `[0.01, 20000]` |
| B      | `joint_sets.0.size_r_max`   |       100 -> 150 |    `[100, 150]` |
| C      | `joint_sets.0.fisher_kappa` |           8 -> 2 |        `[2, 8]` |
| C      | `joint_sets.0.mean_dip_dir` | 90 -> 45 degrees |      `[45, 90]` |

The B/C bounds are reviewed portfolio endpoint envelopes, not permission to
extrapolate beyond them. Mean-direction candidates record the realized
unoriented plane-normal angle. Kappa changes orientation spread while holding
the mean plane fixed.

## Canonical provenance correction

The real smoke exposed that candidate YAML hashing and runtime hashing used
incompatible inputs. `src/core/signature_candidates.py` now projects YAML cases
onto the same generation-feature schema used by `BatchRunner`:

- domain size and grid spacing
- tunnel and borehole geometry
- RQD scan length
- joint-set generation parameters
- global generation parameters

Names, tags, costs, seeds, and run metadata do not alter the generation
signature. Domain IDs use the same projection plus seed/generator identity.
This correction changed catalog parent hashes; old pre-correction hashes must
not be copied into new catalogs.

The smoke also exposed a false one-feature rejection caused by forward
normalization reconstructing P32 `20.0` as `20.000000000000004`. The guard now
restores the probe feature to the parent state before strict hash comparison.

## Small real smoke

Workdir: `validation/campaign_stage4_smoke`

Configuration:

- backend: MLX
- primary seed: 1001 only
- baseline plus four A/B/C screening signatures
- no E repeatability
- no large-scale simulation

Unique real CSV results:

| Case               | Mean Q'\_BH |
| ------------------ | ----------: |
| baseline P32=10    |     252.782 |
| A, P32=20          |     254.277 |
| B, size_r_max=150  |     260.734 |
| C, fisher_kappa=2  |     258.454 |
| C, mean_dip_dir=45 |     256.255 |

All results remained in primary bin 9. No candidate produced a non-zero bin or
proximity coverage direction, so no response-derived Euler candidate was
approved. This is a safe `awaiting_review` stop, not coverage completion.

Current checkpoint summary at handoff:

- status: `awaiting_review`
- stop reason: `no_unattempted_approved_candidates`
- next iteration: 4
- remaining primary bins: 0 through 8
- profile cutoff identified: false
- E repeatability: not requested
- pending response queue: empty

### Smoke artifact warning

The smoke checkpoint preserves the original A ledger record written before the
normalization guard was fixed. It says the A probe changed more than one
feature. That message is stale. Re-evaluation after the fix classified A as
`observed_local_response`, but its coverage delta was still zero, so the final
decision remains no Euler update. Do not use this smoke workdir as a production
resume source; use a fresh workdir for the next validation.

## Validation status

At handoff:

```text
105 tests passed
python compilation passed
git diff --check passed
```

Mock coverage includes interruption/resume, completed CSV reuse, incomplete
output handling, separate E jobs, real A/B/C catalog validation, explicit
absolute target-bin planning, orientation plane-angle evidence, and the P32
normalization rounding regression.

## Remaining work

### 1. Four-seed paired validation (next action)

Run A/B/C with seeds 1001-1004 in a fresh workdir. This is still a bounded smoke,
not the large campaign. It is needed to determine response sign consistency and
whether any candidate supplies a non-zero coverage/proximity direction.

Suggested command:

```bash
conda run -n dlo-cq python validation/run_campaign.py \
  --workdir validation/campaign_stage4_paired_smoke \
  --case cases/highq_portfolio_v2/highq_v2_d1000_angle60_focused_large_base.yaml \
  --seed-start 1001 \
  --seed-stop 1004 \
  --iterations 7 \
  --backend mlx \
  --strategy-catalog validation/highq_strategy_catalog.yml
```

Review the ledger before any continuation. If responses have mixed signs or
`delta_C=0`, do not infer an Euler slope.

### 2. Prove a real response-update iteration

The code path is connected and mock-tested, but the one-seed real smoke did not
produce a non-zero coverage direction. A real response-derived candidate remains
unproven until paired evidence qualifies and the next candidate is executed or
safely rejected at a reviewed bound.

### 3. Add low/internal-gap strategies

The active catalog explicitly targets primary bin 8. There are no approved
strategies for bins 0-7. Full 10-bin coverage cannot be reached from the current
catalog. Add only reviewed parents, target values, bounds, and expected effects;
do not copy the high-Q recipes blindly into lower regimes.

### 4. Register reviewed D cases

D execution is implemented, but the active catalog has no approved discrete
joint-set structure case. D must reference a reviewed case file with a distinct
canonical signature. Never interpolate topology or joint-set count.

### 5. Decide B/C exploration envelopes

Current B/C candidates begin at one endpoint and target the other endpoint of a
reviewed portfolio. If exploration beyond those endpoints is desired, approve
new bounds explicitly. Candidate exhaustion at the current bounds is not
completion.

### 6. Run E repeatability separately

After signature screening is reviewed, choose independent seeds outside the
primary seed range and pass them via repeated `--repeatability-seed`. E must hold
the signature fixed and must not fill coverage bins.

### 7. Large campaign gate

Do not start the 4000-iteration campaign until:

- four-seed A/B/C behavior is reviewed;
- at least one real response-update path is verified or explicitly deemed
  unreachable under approved bounds;
- low/internal and D catalogs are approved if full-grid coverage is required;
- stop/no-improvement criteria and E seeds are agreed;
- a fresh production workdir and exact command are recorded.

Full primary-bin observation remains a coverage milestone only. It does not
identify or validate Q' cutoffs.

## Repository/worktree notes

- `validation/highq_strategy_catalog.yml` and
  `validation/campaign_stage4_smoke/` are currently new/untracked paths unless
  staged before the push.
- Stage 4 runtime changes are in `validation/run_campaign.py` and
  `src/core/signature_candidates.py`; tests are in
  `src/test/test_coverage_rounds.py` and
  `src/test/test_signature_candidates.py`.
- Existing campaign 004 directories and backups are preserved.
- Campaign 003 deletions were intentional user state and must not be restored
  as part of Stage 4 cleanup.
- The worktree contains other specification/config changes from the broader
  QPrime work. Review the staged set before pushing; do not discard unrelated
  user changes.
