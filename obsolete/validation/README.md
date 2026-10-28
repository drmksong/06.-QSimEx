# Isolated Validation Campaign

`run_campaign.py` owns a validation campaign under one work directory.
It does not read production result folders, ledgers, or previous coverage audits.

The current harness validates the isolated simulation -> audit -> ledger path.
After the initial portfolio sweep, each iteration runs only the new candidate.
Audits and profile search use the campaign's cumulative, domain-deduplicated
rows. Their JSON artifacts list all source CSVs; ledger domain/signature counts
refer to the cumulative pool. Probe responses still compare only paired cases
at the same seeds, never pooled rows as independent probes.
Each iteration writes `coverage_audit.json` for the 10-bin primary grid
(the original 11 log-spaced edges from 0.1 to 400, with the first edge replaced
by 0), `profile_boundary_search.json` for the same primary analysis, and
`coverage_audit_20.json` for a 20-bin signature audit using the same rule. The latter
lists signature hashes per bin and bin indices per signature; it does not
change profile classification or claim a cutoff when coverage is filled.
Euler updates require a reviewed parent/probe pair and target bin indices.
With `probe_case_path` in the spec, both cases must appear in the initial
`--case` list. Their results must have distinct signatures and matching seed
sets; only one reviewed generation feature may differ. The campaign measures
the distance from observed primary-grid positions to the specified target bins at
each seed. A decrease in that log-bin distance supplies the Euler direction,
even when the target and adjacent bins are still empty. The closer observed
signature becomes the source for the next candidate. If another signature in
the initial portfolio is closer than the reviewed pair, the campaign uses its
same-seed response against an already executed, single-feature-compatible
probe. Otherwise the ledger requests a reviewed probe from that signature.
Before inferring an Euler direction, the campaign checks measured Q', RQD, and
borehole intersection responses for the same seed set. A reviewed one-feature
density probe with no intersection response, no Q'/RQD response, or no movement
on the primary grid is not treated as failed reachability. It generates another
density probe along the tested direction, doubling the distance from the
original parent in normalized feature space (for example 1.0, 1.2, 1.4, 1.8
within a reviewed 0..2 P32 interval). It is a reachability experiment, not an
Euler step or an inferred gradient. Each probe uses the same seeds. When the
reviewed numerical interval ends, the ledger requests wider exploration
bounds; it does not assert a physical P32 upper limit or unreachable Q'.
Orientation probes additionally require a changed _measured_ borehole-plane
angle; input dip/direction alone is not treated as the realized angle. If
seed-level Q' or relevant intersection/angle responses disagree in sign, the
update waits for repeatability evidence. Accepted probes record local
Q'/RQD/intersection response per normalized feature change; orientation probes
also record Q' response per measured degree. These are local observations,
not universal density/angle thresholds or estimates of statistical significance.
Subsequent iterations compare the generated candidate with its simulated source
at the same seeds.
With no measured distance change outside a supported density reachability
probe, it stops rather than guessing a direction.
No production result is read or automatically used as a probe.

## Strategy catalog campaign

With `--dry-run --initial-csv`, `--strategy-catalog` audits the CSV and writes
`iteration_000/strategy_candidate_plans.json` without materializing cases or
launching simulation. Without `--dry-run`, it executes approved candidates one
at a time, re-audits cumulative domain-deduplicated rows after each candidate,
and atomically updates `campaign_checkpoint.json` and `ledger.jsonl`. Resume an
interrupted run with the same arguments plus `--resume`; complete valid case
CSVs are reused and incomplete attempts are rerun in a new attempt directory.

Each strategy identifies its gap, D/A/B/C feature family, parent case/signature,
expected effect, rationale, and validity constraints. A/B/C entries provide one
explicit family-matched target value and approved bounds. D entries point to a
reviewed discrete case. C mean-orientation changes record the realized plane
angle. Missing approval, target, or bounds stops at review rather than inventing
a value. The default outer-iteration ceiling is 4000.

E repeatability is separate from coverage screening. Add one or more explicit
`--repeatability-seed` values outside the primary seed range to rerun unchanged
signatures. E rows and Q' deltas are checkpointed under `repeatability_E`, but
are excluded from cumulative coverage.

Dry-run example:

```bash
conda run -n dlo-cq python validation/run_campaign.py \
  --workdir validation/campaign_001 \
  --case cases/scenario_11_coverage_low_q.yaml \
  --case cases/scenario_12_coverage_high_q.yaml \
  --seed-start 1001 \
  --seed-stop 1002 \
  --iterations 1 \
  --dry-run
```

The proposed high-Q spec uses two existing one-feature P32 cases and target
10-bin index 8 (`76.146..174.524`). Validate its wiring without simulation:

```bash
conda run -n dlo-cq python validation/run_campaign.py \
  --workdir validation/highq_euler_dry_run \
  --case cases/highq_portfolio_v2/highq_v2_d1000_angle60_focused_large_base.yaml \
  --case cases/highq_portfolio_v2/highq_v2_d2000_angle60_focused_large_base.yaml \
  --seed-start 1001 \
  --seed-stop 1004 \
  --iterations 3 \
  --euler-spec validation/highq_density_euler_proposed.json \
  --dry-run
```

Dry-run prepares configs but cannot predict later candidates before observing
simulation responses. The high-Q spec was approved for this screening run
(`approval_status: approved_for_screening`); this is not calibration approval.
Its `[0.01, 20000]` P32 interval is a reviewed numerical
exploration window, not a physical upper limit or a calibrated cutoff.
Observed-update specs specify `case_path`, `probe_case_path`, `target_region`,
zero-based `target_bins` on the 10-bin primary grid, `feature_bounds`, and `step_size`.
Existing approved specs with explicit `probes` remain
supported but do not automatically measure responses. Generated candidates
are stored under the next iteration and referenced in the preceding ledger
record. Target bins are not inferred from an empty audit bin: a direction
comes from a measured movement among observed bins, not from an empty bin
alone. A filled bin does not imply an identified profile cutoff.
The 20-bin map is an audit only; its bin indices must not be supplied as
`target_bins` without remapping the target Q' interval to the 10-bin grid.

## 2026-09-27 Handoff (Historical)

- Implemented: isolated same-seed parent/probe screening, 10-bin Euler target,
  20-bin audit, cumulative domain-deduplicated coverage/profile, and widening
  density reachability probes. The CSV loader now accepts UTF-8 BOM.
- `campaign_003/iteration_000/simulation/` contains completed MLX results for
  the P32 10/20 pair at seeds 1001-1004; no production CSV was imported.
  The first post-simulation attempt failed when the BOM-prefixed `case_name`
  was not parsed. The subsequent run produced audits, a profile search and a
  ledger record, but **no iteration 1 candidate**. Its `next_action` is
  `await_physical_probe_response` with `needs_repeatability` on `Qp_bh_mean`:
  the per-seed Q' differences change sign, while both cases remain in 10-bin 9
  (target is bin 8). `profile_search_status` is `not_identifiable`.
- Next: separate "no reliable Euler slope" from density reachability. When
  same-seed Q' differences conflict but the probe stays in the same bin,
  continue a reviewed wider _density experiment_ without declaring an Euler
  direction; keep the Q' conflict in the ledger. Test against the saved round
  0 CSV and a multi-iteration mock before another large-scale simulation.
- Next: add a safe way to replay completed iteration 0 without rerunning it, or
  start a new campaign workdir. Re-entering the current command has no resume
  semantics and rewrites files in `campaign_003`. Do not overwrite those results
  before deciding how to preserve/reuse them. Treat `min_domains=1` profile
  `identified` as a screening signal, not a validated cutoff; review the early
  stop rule before a larger campaign.

The referenced `campaign_003` results were deleted on 2026-10-01 at the user's
request. The block above records the state at handoff time only; do not use its
paths as current inputs.

## 2026-10-01 Resume

The observed one-iteration stop in `campaign_003` was not caused by the Euler
candidate failing to attach to the loop. The campaign requested three iterations,
but iteration 0 stopped at `await_physical_probe_response`: same-bin seed-level
Q' responses had conflicting signs, and the runner treated that as a hard stop.
For a density probe with no 10-bin movement, the runner now records that conflict
and continues as a wider density reachability probe without inferring an Euler
slope. `--iterations` remains a hard iteration budget; its default is 1.

`--initial-csv` copies a completed borehole CSV into iteration 0, so that
large-scale simulation is not repeated. By default, a non-empty workdir is
rejected. `--force-overwrite` first archives an existing isolated campaign as a
sibling `*.backup-<timestamp>` directory, then starts a fresh campaign at the
requested path. It does not delete the previous results. To rerun from the
case inputs with a maximum 4000-iteration budget and four seeds per signature, run:

`--iterations` is an upper bound on outer signature-update iterations, not a
seed count. `--seed-start` and `--seed-stop` specify inclusive seed IDs reused
for each case/signature, so 1001 through 1004 means four seeds. Paired parent
and probe comparisons require identical seed sets. If `--initial-csv` is used,
its seed set must match the newly simulated probe's seed set exactly.

```bash
conda run -n dlo-cq python validation/run_campaign.py \
  --workdir validation/campaign_004_qprime_resume \
  --case cases/highq_portfolio_v2/highq_v2_d1000_angle60_focused_large_base.yaml \
  --case cases/highq_portfolio_v2/highq_v2_d2000_angle60_focused_large_base.yaml \
  --seed-start 1001 \
  --seed-stop 1004 \
  --iterations 4000 \
  --backend mlx \
  --euler-spec validation/highq_density_euler_proposed.json \
  --force-overwrite
```

Iteration 0 runs the two base/probe cases; iterations 1-3999 can run generated
candidates. Reaching the configured target bin advances the search to the
nearest still-unobserved 10-bin profile interval; it does not end the campaign.
Coverage exploration ends when all ten primary profile bins are observed or the
iteration budget/another logged stop condition is reached. The 4000 value is a
ceiling, not a requirement to run that many iterations. Full bin coverage is not
itself a cutoff-identification result.
The previous campaign_004 directory is moved to a timestamped backup. After the command completes,
review `campaign_manifest.json`, `ledger.jsonl`, each iteration's coverage audits,
`signature_overlap_20.json`, and candidate provenance before deciding whether to
extend the campaign. The overlap report identifies signatures that add exclusive
Q' coverage and signatures whose observed bins are already covered by others.
It only informs future screening priority: all source signatures and rows are
preserved, and no candidate is automatically discarded.

The campaign does not yet automatically select a smaller active signature
portfolio; use the overlap report to review which signatures should receive
additional seeds. A profile result of `identified` is only a screening signal
(`min_domains=1`): it no longer stops a campaign before its requested iteration
budget unless `--stop-on-identified` is explicitly supplied.

If a measured density direction reaches the P32/spacing bounds in the reviewed
Euler spec, the runner records `await_wider_density_bounds` rather than claiming
that no physical response or Euler direction was observed. It does not widen
the approved bounds automatically; review and approve a wider numerical search
interval before starting another campaign.

If seed-level Q' response signs conflict, the runner does not infer an Euler
slope. For density probes it may still continue the reviewed reachability step
when target-bin proximity is unchanged or improves; if coverage moves farther
from the target, it records `await_physical_probe_response` instead.

Generated case names are reset to the root case name plus the current candidate
ID on every iteration. Do not concatenate the full parent candidate name: batch
output paths repeat the case name in both the directory and CSV filename and can
exceed filesystem component limits after several updates.

Batch CSV provenance (`generation_signature_hash`, `domain_id`, and generator
version) is computed from the generated case and is not overwritten by inherited
YAML tags. Density reachability candidates update their identity tags as well, so
paired-probe validation sees the newly generated signature.
