# DFN-to-RQD Signature Search Log

## 2026-11-04 09:14 +09:00 — Work paused for user travel

The user said to resume after returning from travel. The urgent P0 input-driven raw-RQD
plan remains staged; no implementation, baseline3 creation, preview, persistent DB/manifest/
DFN write, or simulation is authorized before the user returns and instructs continuation.

## 2026-11-04 09:12 +09:00 — Urgent input-driven raw-RQD plan recorded

The user requested a staged plan to remove conflicts where raw-RQD hard-coded behavior
rejects or overrides input. Marked P0/urgent and planned only; implementation is deferred
until the user returns from travel and resumes the task.

Plan target: new `config/rqd_exploration_main_baseline3.yml`, raw-only loader/preview,
Jn15/four-set + Jn20/five-set, five initial signatures each, design seeds 36/40,
realization seed 43, current 30x20x20 m domain, P32 [1,100], radii [1,150] m. Input must
govern domain/measurements, bounds, sample count, and realization seed in both preview and
run; main workflow and baseline2 remain unchanged. Preserve execution/storage safety gates.

Before implementation, clarify how to represent P32 coordinate step: current absolute
0.1 step is not aligned with log-coordinate bounds. Planned gates cover raw-only input
loading, no hidden sample/seed/bounds overrides, proposal-bound checks, effective-config
fingerprinting, focused tests and non-persistent preview. No code/input/DB/manifest/DFN
change, preview, or simulation was performed.

## 2026-11-04 07:35 +09:00 — Raw-RQD hard-coded behavior audited

The user asked to audit input-vs-code behavior before implementing Jn15/Jn20 inputs. No
code, config, DB, manifest, DFN, or simulation was changed.

Geometry is read from the normalized input, but the shared parser fixes BH interval and
face advance to 1 m and the main wrapper requires all baseline geometries to match. The
raw command loads `MainConfig`: its loader requires baseline Jn2/4/9/15 and permits Jn20
only as a separate optional initial input. It cannot represent a focused Jn15/Jn20-only
set.

The parser reads P32/radius bounds from YAML, then the main loader requires P32
`[0.01,10]` and radii `[1,150]`; raw coordinate moves use a separate global `AXES` table
with fixed steps and those same boundaries. A requested P32 `[1,100]` is therefore
rejected by the loader and cannot govern local proposals. Raw-RQD also overrides YAML
`sample_count` with 10 LHS signatures per Jn. Preview uses each design's realization
seed, while execution uses `policy.initial_seed` (both currently 43). Search policy
hard-coded in code includes five axes/order/steps, one-axis +/- proposals, the 1 m support
floor, support-weighted-mean ranking, strict-improvement center promotion, one seed/run
per signature, and BH-only measurements.

Safety/data-contract guards (separate raw DB, schema4, explicit execution confirmation,
MLX-only execution, raw RQD `[0,100]`) should remain explicit invariants unless a specific
need is approved. A future design should use a raw-only loader for
`rqd_exploration_main_baseline3.yml`, take geometry/measurement/sample count/realization
seed from one input source, and derive proposal bounds from the input design. Implementation
is not approved yet; no tests or previews were run for this audit.

## 2026-11-03 21:54:33 KST +0900 — Lowest-RQD signatures analyzed

Primary ranking uses the approved support-weighted mean. The five lowest signatures are
all Jn=15: mean 69.029 (selected center), 70.407 (set-4 minimum radius +0.1), 71.420
(set-4 minimum radius -0.1), 71.502 (set-4 mean dip +5), and 71.893 (set-3 mean dip
direction +5). None of these one-axis neighbors beats the center.

By single-location minimum, the five lowest are 23.212 at 14 m (signature mean 74.776),
25.032 at 28 m (74.800), 27.331 at 12 m (73.682), 28.386 at 8 m (69.029, selected
center), and 29.929 at 6 m (76.948); all are Jn=15. The 23.212 candidate changes
set-1 mean dip direction +5; set-2 P32 -0.1, maximum radius +0.1, mean dip direction +5;
and set-3 mean dip -5 relative to center. It lowers one interval but raises signature mean
by 5.747, demonstrating the different objectives.

The completed fixed-step neighborhood had 11/20/30/40 direct one-axis neighbors for
Jn 2/4/9/15, with no strictly lower mean. Best-neighbor mean deltas were +1.535, +0.097,
approximately 0.000 (not lower), and +1.378. The current search is at a one-axis local
minimum. A multi-axis or larger-step neighborhood around the Jn=15 center is a plausible
unvalidated next approach for lowering mean. The low-minimum multi-axis signature is a
separate candidate only if the user prioritizes minimum local RQD over mean. Keep
`size_alpha`/`fisher_kappa` fixed unless separately approved. Analysis only; no code, DB, or
simulation changes.

## 2026-11-03 21:49:32 KST +0900 — Search completed; full-range coverage is insufficient

The read-only DB/final event-85 report review found `targets_complete`: 180 signatures
(40 initial LHS plus 140 coordinate neighbors), distributed 27/39/40/74 across Jn
2/4/9/15. All 180 attempts succeeded. The cumulative dataset has 5,400 valid BH intervals
with 1 m support each (5,400 m total), with no invalid or unsupported BH intervals.

Raw RQD range: 23.212–100; support-weighted mean: 85.777. Counts by 10-point band:
10–<20 0, 20–<30 5, 30–<40 51, 40–<50 76, 50–<60 166, 60–<70 500,
70–<80 845, 80–<90 1,060, 90–100 2,697; exact 100: 1,414. No signature touched
10–<20, only five touched 20–<30, and all 180 touched 90–100. The complete run therefore
does not provide sufficient coverage over the full 10–100 range, although higher RQD bands
are well populated.

Per-Jn observed range / weighted mean / selected-center mean: Jn2 41.08–100 / 88.95 /
78.66; Jn4 61.29–100 / 95.88 / 92.71; Jn9 40.91–100 / 90.12 / 87.12; Jn15 23.21–100 /
76.95 / 69.03. This is not a measurement-failure gap: all BH intervals are valid and
supported. It reflects the search objective and scope: minimizing weighted mean by bounded
local coordinate moves, not stratified coverage across RQD bins; `size_alpha` and
`fisher_kappa` stay fixed after center selection. The 5,400 intervals are clustered within
180 signatures, and signatures per Jn are uneven. Failure to observe 10–<20 does not prove
it is impossible in the full parameter space. A coverage-oriented next run would require
user-approved bin quotas/selection rules; no further run or code change was made.

Final report: `/Users/myungkyusong/QSimExOutput/raw-rqd-signature-neighborhood-20261103-2107-reports/raw-rqd-25e1e181eb41ebd933844361da1b126de187e49adb3d0800348b9ceb635f593c/event-85/summary.json`.

## 2026-11-03 21:35:42 KST +0900 — User-interrupted run is resumable

Read-only inspection of the new
`raw-rqd-signature-neighborhood-20261103-2107.sqlite` found status `paused`,
reason `user_interruption`, resume phase `exploration`, round 7, 44 consumed starts, and
two queued tasks. All 44 starts and attempts succeeded; there is no running or failed
attempt. The current raw config fingerprint matches the stored value and uses the
30x20x20 domain. The user can rerun the same command with the same config, DB, output
directory, and `--confirm-execution`; completed work will be skipped and the queue resumed.
Runtime identity is checked again by preflight. No DB changes or simulations occurred
during this diagnosis. Await the user's rerun/results.

## 2026-11-03 21:34:04 KST +0900 — Raw-RQD progress output made human-readable

The raw-RQD console now replaces repeated run/input hashes with Jn, round/phase, the
signature axis and before-to-candidate values with signed delta, seed, and role. Completion
reports supported BH interval count, total support, raw-RQD min/max/support-weighted mean,
and candidate-minus-center mean; round completion reports center selection or movement.
Runner start/heartbeat/skip/failure/completion messages suppress raw job hashes, and the
observation count is labeled `BH-observations`. Full identifiers remain in persisted
SQLite/events/reports; non-raw runner output retains its prior default labels.

Verification: 18 focused raw-search/runner tests passed in `dlo-cq`; compileall, Pylance
syntax and signature-compatibility checks, and `git diff --check` passed. No simulation,
persistent DB, or manifest was created.

## 2026-11-03 21:11:08 KST +0900 — Local coordinate axes confirmed

The user confirmed using only the five existing local axes: `p32_m2_per_m3`,
`size_r_min_m`, `size_r_max_m`, `mean_dip_deg`, and `mean_dip_dir_deg`. Initial LHS still
samples `size_alpha` and `fisher_kappa`, but neither is changed by the local neighborhood
search because no coordinate steps for them were approved. The raw-RQD preview/run summary
now reports the actual local axes.

## 2026-11-03 21:07:34 KST +0900 — Controlled signature-neighborhood search implemented

The user approved a fresh raw-RQD flow: 10 LHS starts per Jn 2/4/9/15 (40 total), measured
once with the configured seed. For each Jn, the lowest supported-weighted-mean BH RQD
signature becomes the sole active center. Subsequent rounds test bounded +/- small-step
neighbors along one signature coordinate at a time, in cyclic order; a center moves only to
a candidate with a strictly lower weighted mean. Equal responses keep the current center.
This is coordinate search, not Euler/gradient updating, and there is no RQD pass threshold.

The raw-RQD path now avoids face measurement/intersections while retaining planned face
locations in the frozen manifest; those locations are finalized as `missing` with the
explicit BH-only reason. Per-signature supported BH locations, RQD/support, center
transitions, parameter changes, and candidate/reference RQD deltas are included in reports.
This supersedes the earlier Stage 2 reference-ranking proposal loop. A new database and
output directory are required; the previous failed Stage 2 database is not reused.

Validation: 52 focused raw-search/measurement/runner/store tests passed under `dlo-cq`;
compileall, Pylance syntax and signature-compatibility checks, and scoped
`git diff --check` passed. Preview tests confirm 40 starts across four Jn values with no
simulation or database write. Separate main-workflow/main-store selectors were attempted
but are blocked by their test configuration's `main and baseline geometry/measurements
must match` error; no unrelated fix was made. No persistent DB, manifest, or simulation was
created.

User-run command (not executed here):

```sh
conda activate dlo-cq
python -u run_rqd_exploration.py raw-rqd run \
  --config config/rqd_exploration_main.yml \
  --database /Users/myungkyusong/QSimExOutput/raw-rqd-signature-neighborhood-20261103-2107.sqlite \
  --output-dir /Users/myungkyusong/QSimExOutput/raw-rqd-signature-neighborhood-20261103-2107-reports \
  --confirm-execution
```

Wait for the user to execute and report results before continuing.

## 2026-11-03 20:04:20 KST +0900 — User-run Stage 2 search paused; diagnostic

Read-only inspection of
`/Users/myungkyusong/QSimExOutput/raw-rqd-stage2-20261103-1949.sqlite` and its report
found run status `paused`, reason `execution_error`. It consumed 10 starts: 9 succeeded and
1 failed. All 9 completed signatures belong to Jn=2 and seed 43, each with 60 supported-valid
BH intervals (540 BH observations total). The database also contains 549 face observations:
the shared `measure_realization` pipeline computes BH and face data even though the raw-RQD
summary filters to BH.

The 10th task was a Jn=2 LHS candidate. Face measurement raised
`ValueError: scanline intersections contradict an empty supported face` at
`src/euler_campaign/profiles.py:292`. The controller paused and returned a partial summary;
the CLI printed that summary as JSON with the per-signature RQD metrics. It did not reach
reference-based adaptive proposals, so Stage 2 reference ranking and parameter/RQD delta
recording were not exercised in this run.

The user's clarified goal is to control a reference signature and explore its neighborhood.
Current proposals use bounded fixed-axis perturbations and LHS; no Euler/gradient update is
implemented. RQD results observed: 9 Jn=2 signatures, support-weighted means from 87.29 to
100.00; lowest mean is 87.29 (signature prefix `d1f9940deb`, min 42.30, max 100.00).
The full per-signature summary is in
`/Users/myungkyusong/QSimExOutput/raw-rqd-stage2-20261103-1949-reports/raw-rqd-0f3c2f11fce4fe0e690ccf03a61c488d4aade3ffce75226e9b428cde03307bce/event-1/summary.json`.
No code change, database write, rerun, or automatic retry was made during this diagnosis.

## 2026-11-03 19:49:19 KST +0900 — Stage 2: rank references and record response deltas

The user authorized Stage 2 and specified that they will perform the real run. Within each
Jn condition, the raw-RQD controller now ranks measured signatures by support-weighted mean
raw BH RQD, lowest first, then signature ID; signatures without supported observations are
last. The existing bounded proposal engine and rotating reference selection remain. This is
reference prioritization only, not a pass/fail decision or RQD-based stop condition.

Each completed adaptive round now persists the reference and candidate weighted means,
candidate-minus-reference RQD delta, and changed signature-axis values/deltas by joint set
in the SQLite event and JSON report. Initial LHS signatures have no measured parent and do
not produce an adaptive delta. The raw-search fingerprint version was advanced to distinguish
the updated proposal policy.

Validation in `dlo-cq`: 9 focused raw-RQD tests passed, including support-weighted reference
ordering and persisted response-delta evidence. `compileall` and `git diff --check` passed.
No persistent database, manifest, or simulation was created. The user will run the command
provided with this handoff.

## 2026-11-03 19:41:41 KST +0900 — Stage 1: remove pass and seed-verification rules

The user authorized Stage 1. The raw-RQD path now measures continuous raw BH RQD response,
not whether a signature passes a threshold. Removed the `<=10` target/pass count, the
seed-43 positive-support requirement, verification seeds 44–46, paired-progress decisions,
and the three-round stagnation gate. One realization per signature uses the configured
initial seed (43 in the current YAML) only as reproducibility/provenance. The main start
limit and review checkpoint remain.

Per-signature summaries now provide valid supported observation count, raw min/max, and
support-weighted mean. The user approved the mean for guiding future candidate updates;
Stage 1 only reports it, and Stage 2 will use it to steer signature proposals and record
parameter/RQD deltas. No `<=10` cutoff remains in preview or run summaries.

Validation in `dlo-cq`: 7 raw-RQD tests passed. The preview emitted 20 candidates across
Jn 2/4/9/15, with one seed and no simulation or DB write. `compileall`, Pylance
syntax/diagnostics, and `git diff --check` passed. No persistent DB, manifest, or simulation
was created.

### Remaining work at Stage 1 handoff

1. Stage 2: guide bounded signature proposals using support-weighted mean raw RQD and record
   signature-parameter changes alongside raw BH RQD changes; do not define pass/fail.
2. Stage 3: report the per-signature and per-location relationship and candidate/reference
   deltas.
3. Stage 4: add focused in-memory tests for update direction and the measurement/report
   contracts.
4. Stage 5: hand off the command for user-run execution; do not run it here.

## 2026-11-03 19:07:53 KST +0900 — Main-method raw-RQD search implemented

The user approved the bounded implementation: reuse the current main exploration method,
active Jn 2/4/9/15 signature templates and YAML bounds, replacing the bin-conditioned
objective with direct raw BH RQD `<= 10`. The retained positive-support rule is seed 43
positive plus at least two positive results from seeds 44–46 after all three are observed.
Current proposal, paired-progress, start/review cap, and three-round stagnation mechanics
remain; no Q-prime/bin/Jr/Ja objective or `physical_rqd_floor` filter is used.

Implemented `RawRqdController`, a separately fingerprinted `raw-rqd run` command, and
per-signature supported-valid raw BH min/max/at-or-below-10 summaries. The command requires
explicit database/output paths and `--confirm-execution`; it rejects databases containing
pilot/main manifests or main-control runs. The real entrypoint preview emitted 20 candidates
across Jn 2/4/9/15 and reported no simulation or database write.

Validation in `dlo-cq`: raw-RQD tests 7/7, main-controller tests 17/17, and main-workflow
tests 10/10 passed. `compileall`, Pylance syntax/diagnostics, and `git diff --check` passed.
The broader `test_rqd_main_*.py` selector had 61 passes and one error because
`test_resume_stagnation_guard_does_not_cut_an_active_verification_block` calls a missing
`MainController._plan_stability`; it was not changed in this implementation. No persistent
database, manifest, or simulation was created. The actual run remains unauthorized and was
not started.

## 2026-11-03 18:47:50 KST +0900 — Generation-free raw-RQD slice implemented

Added `src/rqd_exploration/raw_rqd_search.py` and routed the explicit
`run_rqd_exploration.py raw-rqd` prefix to it, leaving the existing CLI implementation
untouched. `preview` produces deterministic signature inputs from existing validated YAML
LHS designs. Pure helpers extract BH-only raw RQD, preserve invalid/excluded observations,
and summarize supported raw values and counts at/below RQD 10 without Q-prime clamping.
No new directory, user DB access, database write, manifest, or simulation was made.

Validation in `dlo-cq`: `python -m unittest src.test.test_rqd_raw_search -v` passed (3 tests);
`python run_rqd_exploration.py raw-rqd --help` exposed the isolated preview command, and an
actual entrypoint preview produced 10 deterministic candidates with both no-simulation and
no-database-write flags. `compileall` and `git diff --check` passed for checked paths. The
first test attempt failed only because the repository was not the command working directory;
the corrected repo-local invocation passed. A preview-output test capture issue was fixed
before the focused suite passed.

This is a generation-free foundation only. It does not execute DFNs, persist measurements,
adapt signature proposals from observed RQD, infer a relationship model, or define independent
validation success. Those remain blocked on the decisions in `DFN_RQD_Imp.md`.

## 2026-11-03 18:44:12 KST +0900 — New exploration path authorized

The user approved preparing a separate code path to explore only the DFN-signature/raw-RQD
relationship, validate it independently, and apply reviewed findings to the main simulation
later. The user explicitly directed that no new folder be created because the existing
`src/rqd_exploration/` package and `run_rqd_exploration.py` entry point already exist.

### Why the scope drifted

The strategy preserved high-to-low signature updating as a **complete v4/main objective**,
but a staged-scope decision separated that objective from the immediate fixed-LHS pilot.
The pilot did not perform automatic signature updates. T011 was subsequently implemented
as a Q-prime-bin-conditioned controller: it searched a particular `(bin, Jn, Jr, Ja)` target,
applied the derived `physical_rqd_floor` reachability filter, and stopped on its separate
paired-progress/stagnation rule. Those mechanisms answer whether a signature supports a
fixed Q-prime target; they do not directly search for signatures producing low raw RQD.

The naming obscured the boundary: `run_rqd_exploration.py` is the umbrella pilot CLI, and
its current commands include both pilot and T011 main workflows. Its name did not mean it
already contained a raw-RQD-only signature search. Recent read-only DB inspection confirmed
that the stopped run had no supported raw BH observation at RQD <= 10, and that some
theoretically low-RQD bin-6 targets were filtered before evaluation.

### Agreed implementation boundary

- Reuse the current `src/rqd_exploration/` package; create no directory.
- Add a clearly isolated raw-RQD search path under the existing entry surface and preserve
  current command behavior.
- Reuse DFN generation and raw BH measurement, but do not use Q-prime/bin/Jr/Ja target
  scoring as the RQD-only objective.
- Keep search data separate from existing pilot/main databases.
- No code, database, policy, or simulation was changed/run in this step.

### Pending before adaptive execution design

The user's conceptual target is raw RQD <= 10, but support/replicate success criteria,
starting signature domain, seed policy, adaptive update method, persistence format, and
resource cap are not specified. The implementation plan records these as decisions rather
than assuming values. Generation-free preview and unit-tested raw-observation processing
can proceed; actual simulation and DB initialization/writes require separate authorization.

### Evidence references

- Strategy staged-scope decision: `RQDExplorationStrategy_20261026/plan.md`, §1.1 and the
  2026-10-31 18:56 KST decision.
- T011 implementation and active policy: `MainSimulation_T011/plan.md`, §2 and §5.
- Raw low-RQD diagnosis: `ImplementationPlan_v4.md`, latest low-RQD signature diagnosis.
- Reusable raw measurement: `src/rqd_exploration/measurement.py`.
- Current target-based search: `src/rqd_exploration/main_analysis.py`,
  `src/rqd_exploration/main_controller.py`, and `src/rqd_exploration/main_design.py`.
