# Isolated Validation Campaign

`run_campaign.py` owns a validation campaign under one work directory.
It does not read production result folders, ledgers, or previous coverage audits.

The current harness validates the isolated simulation -> audit -> ledger path.
After the initial portfolio sweep, each iteration runs only the new candidate.
Audits and profile search use the campaign's cumulative, domain-deduplicated
rows. Their JSON artifacts list all source CSVs; ledger domain/signature counts
refer to the cumulative pool. Probe responses still compare only paired cases
at the same seeds, never pooled rows as independent probes.
Each iteration writes `coverage_audit.json` for the 10-log-bin update/profile grid,
`profile_boundary_search.json` for the 10-bin primary analysis, and
`coverage_audit_20.json` for the 20-log-bin signature coverage map. The latter
lists signature hashes per bin and bin indices per signature; it does not
change profile classification or claim a cutoff when coverage is filled.
Euler updates require a reviewed parent/probe pair and target bin indices.
With `probe_case_path` in the spec, both cases must appear in the initial
`--case` list. Their results must have distinct signatures and matching seed
sets; only one reviewed generation feature may differ. The campaign measures
the distance from observed 10-bin positions to the specified target bins at
each seed. A decrease in that log-bin distance supplies the Euler direction,
even when the target and adjacent bins are still empty. The closer observed
signature becomes the source for the next candidate. If another signature in
the initial portfolio is closer than the reviewed pair, the campaign uses its
same-seed response against an already executed, single-feature-compatible
probe. Otherwise the ledger requests a reviewed probe from that signature.
Before inferring an Euler direction, the campaign checks measured Q', RQD, and
borehole intersection responses for the same seed set. A reviewed one-feature
density probe with no intersection response, no Q'/RQD response, or no movement
on the 10-bin grid is not treated as failed reachability. It generates another
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
  --workdir validation/campaign_003 \
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
Its `[0.01, 200]` P32 interval is a reviewed numerical
exploration window, not a physical upper limit or a calibrated cutoff.
Observed-update specs specify `case_path`, `probe_case_path`, `target_region`,
zero-based `target_bins` on the 10-bin grid, `feature_bounds`, and `step_size`.
Existing approved specs with explicit `probes` remain
supported but do not automatically measure responses. Generated candidates
are stored under the next iteration and referenced in the preceding ledger
record. Target bins are not inferred from an empty audit bin: a direction
comes from a measured movement among observed bins, not from an empty bin
alone. A filled bin does not imply an identified profile cutoff.
The 20-bin map is an audit only; its bin indices must not be supplied as
`target_bins` without remapping the target Q' interval to the 10-bin grid.

## 2026-09-27 Handoff

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
  0 CSV and a multi-iteration mock before another GPU run.
- Next: add a safe way to replay completed iteration 0 without rerunning it, or
  start a new campaign workdir. Re-entering the current command has no resume
  semantics and rewrites files in `campaign_003`. Do not overwrite those results
  before deciding how to preserve/reuse them. Treat `min_domains=1` profile
  `identified` as a screening signal, not a validated cutoff; review the early
  stop rule before a larger campaign.
