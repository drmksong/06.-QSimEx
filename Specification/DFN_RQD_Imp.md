# DFN-to-RQD Signature Search Implementation Plan

**Handoff (2026-11-04 09:14 +09:00):** Work is paused until the user returns from travel
and instructs us to continue. The P0 plan below is not implementation approval. Do not
create baseline3, edit source, preview, write DB/manifest/DFN, or run simulations.

## 🚨 Urgent P0: input-driven raw-RQD follow-up (2026-11-04 09:12 +09:00)

**Planned only; waiting for the user to return and resume.** Do not implement, create
baseline3, preview, write DB/manifest/DFN, or run simulations yet.

Ordered handoff:
1. Confirm baseline2 fields to carry forward and the P32 step representation; current
   absolute +/-0.1 conflicts conceptually with log-coordinate P32 bounds.
2. Add `config/rqd_exploration_main_baseline3.yml` for Jn15/4 sets and Jn20/5 sets, using
   the accepted values: LHS 5 each, design seeds 36/40, realization seed 43, domain
   30x20x20 m, P32 [1,100], radius [1,150] m. Preserve other input fields unless changed
   by the user.
3. Add a raw-only loader/preview path that reads baseline3 directly; do not weaken the
   main loader or change main Jn20 exclusion.
4. Use input values consistently for geometry, measurements, bounds, LHS count, seeds,
   and fingerprints. Generate coordinate proposals within per-set input bounds; no hidden
   fallback/override.
5. Test 10 deterministic initial signatures (5 per Jn), Jn/set counts, domain, seeds,
   bounds, proposal edges, fingerprint invalidation, and unchanged main workflow.
6. Run `dlo-cq` focused validation and in-memory preview only. Hand preview to user; any
   persistent manifest/DB, DFN generation, or simulation needs separate explicit approval.

Detailed stages, acceptance criteria, and scope boundaries are in
[ImplementationPlan_v4.md](./ImplementationPlan_v4.md). No source or input file has been
created or changed for this plan.

**Previous status (2026-11-04 07:35 +09:00):** Raw-RQD hard-coded behavior audit completed
as requested before implementation. Geometry is read from normalized input, but BH/face
intervals are fixed to 1 m. The raw command consumes `MainConfig` whose loader requires
Jn2/4/9/15 baselines and treats Jn20 only as optional initial input; it cannot express the
requested Jn15/Jn20-only set. The main loader re-locks bounds to P32 [0.01,10]/radius
[1,150] after YAML parsing, and raw coordinate proposals use a separate global `AXES`
table. LHS count is hard-coded to 10 per Jn despite YAML `sample_count`; preview and run
also use different seed fields (design seed vs policy initial seed; both currently 43).
Search policy has fixed axes/steps, one-axis +/- moves, 1 m supported-observation floor,
support-weighted-mean ranking, strict-improvement center promotion, one seed/run and BH-only
measurement. Safety/storage invariants were identified separately.

Next design candidate: raw-only loader for `rqd_exploration_main_baseline3.yml`; use the
input as the shared source of geometry, measurements, bounds, sample count and realization
seed; derive local proposal limits from each design's declared bounds; preserve main
workflow and explicit execution/storage safety gates. The user has not authorized code
implementation. No source/config change, preview, database/manifest/DFN write, or simulation
was performed. Existing five-signature analysis remains below.

**Previous status (2026-11-03 21:54:33 KST +0900):** Analysis of the five lowest signatures
by the approved support-weighted mean found all are Jn=15; the selected center mean is
69.029 and the next four one-axis neighbors are higher (70.407–71.893). The five lowest
single-location minima range from 23.212 to 29.929, but the 23.212 signature has mean
74.776, 5.747 above the center. All 11/20/30/40 direct one-axis neighbors around the
selected centers (Jn 2/4/9/15) failed to strictly improve the mean. A multi-axis or
larger-step neighborhood around the Jn=15 center is a plausible but unverified approach.
The low-minimum candidate is relevant only if minimum local RQD, rather than mean, is the
chosen objective. No code, DB, or simulation changes were made.

**Run status (2026-11-03 21:49:32 KST +0900):** The signature-neighborhood run completed
(`targets_complete`) with 180 signatures and 5,400 valid, supported 1 m BH observations.
Raw RQD spans 23.212–100; 10–<20 has no observations and 20–<30 has only five. All runs
succeeded, so the low-range gap is not a measurement failure. The search minimizes
support-weighted mean with bounded local moves rather than stratifying the 10–100 range;
the results do not prove lower RQD is impossible outside these explored neighborhoods. A
coverage-oriented follow-up requires user approval of target bin quotas and selection rules.
No new run or code change was made during diagnosis.

**Previous status (2026-11-03 21:35:42 KST +0900):** The user-interrupted neighborhood run
was resumable. Read-only inspection found DB status `paused/user_interruption`, resume phase
`exploration`, round 7, 44 successful starts/attempts, two queued tasks, and no running or
failed attempt. The current raw config fingerprint matched the stored one; the domain was
30x20x20. The same command resumed completed work and continued the queue.

**Progress-log status (2026-11-03 21:34:04 KST +0900):** Raw-RQD progress output now replaces
repeated run/input hashes with readable Jn/round/phase, parameter changes, seed/role, and
BH RQD/support summaries. Raw runner start/heartbeat/skip/failure/completion messages hide
job hashes; persisted identifiers are retained. The generic runner's default output is
unchanged. Eighteen focused raw-search/runner tests passed under `dlo-cq`, along with
compileall, Pylance syntax/signature checks, and scoped diff checking. No simulation or
persistent DB/manifest was created.

**Search status (2026-11-03 21:11:08 KST +0900):** The approved signature-neighborhood
workflow is implemented. It generates 10 fresh LHS signatures per Jn 2/4/9/15 (40 total),
evaluates each once with the configured realization seed, and chooses one center per Jn
using the lowest support-weighted mean over supported-valid BH intervals. It then evaluates
bounded one-axis +/- small-step neighbors in cyclic order and promotes only a strictly
lower-mean candidate. This is coordinate search, not Euler/gradient updating. The former
Stage 2 reference-ranking proposal loop below is superseded; its prior database is not reused.

The user confirmed the local axes are the five existing `AXES`: P32, minimum/maximum
radius, mean dip, and mean dip direction. LHS also varies `size_alpha` and `fisher_kappa`,
but these remain fixed per selected center because local steps for them were not approved.
The preview and run summary expose the selected axes.

Raw-RQD runs no longer compute face measurements/intersections. Planned face locations
remain in the frozen manifest for schema compatibility and are finalized as `missing` with
reason `not measured: raw-RQD search is BH-only`. Reports include signature inputs,
supported-valid per-location BH RQD/support, center changes, and candidate/reference
parameter and RQD deltas. Focused `dlo-cq` validation passed 52 tests; compileall, Pylance
syntax/signature checks, and scoped `git diff --check` passed. Preview tests verify 40
candidates, four Jn values, and no simulation/DB write. Main workflow/store regression
selectors are blocked by a test-config geometry/measurement mismatch; that separate issue
was not changed. No persistent DB, manifest, or simulation was created. Next is the user's
execution and result review; wait for those results.

**Latest status (2026-11-03 20:04:20 KST +0900):** Stage 2 implementation is complete, but
the user's run at `/Users/myungkyusong/QSimExOutput/raw-rqd-stage2-20261103-1949.sqlite`
paused with `execution_error`; it did not complete the search. There were 10 starts, 9
succeeded realizations, and 1 failed realization. The 9 completed signatures are all Jn=2,
seed 43, with 60 supported-valid BH observations each (540 BH observations total); the DB
also contains 549 face observations because the shared measurement path computes faces too.
The failed task was the 10th Jn=2 LHS candidate. Its face-measurement path raised
`ValueError: scanline intersections contradict an empty supported face` in
`src/euler_campaign/profiles.py`; this is not an RQD threshold or Stage 2 ranking failure.
The run has not reached reference-based local proposals, so no adaptive RQD/parameter deltas
were produced. This implementation uses fixed bounded coordinate perturbations plus LHS,
not an Euler/gradient update. Do not rerun this DB unchanged: the failed attempt is persisted
and automatic retry is disabled. No code change or rerun was performed during diagnosis.

## Stage 2 implementation status (2026-11-03 19:49:19 KST +0900)

Within each Jn condition,
measured signatures are ordered by support-weighted mean raw BH RQD, lowest first, with
signature ID as the tie-breaker and signatures without supported measurements last. The
existing bounded proposal engine and its rotating reference selection remain in use. Each
completed adaptive round records the reference/candidate weighted means, their RQD delta,
and per-joint-set signature parameter deltas in the SQLite event and JSON report. Initial
LHS exploration has no measured reference and therefore emits no response-delta record.
This is not an Euler method: it does not estimate an RQD gradient or use observed RQD deltas
to calculate parameter steps. There is still no pass/fail rule, RQD threshold, surrogate
model, or RQD-based stop condition.

## Purpose

Build a separate exploration path to measure how DFN signature changes affect the
continuous **raw BH RQD** response. Preserve the observed RQD for each valid BH unit with at
least 1 m of measured support, and use the evidence to guide later signature updates from
higher to lower RQD. There is no pass/fail threshold or seed-verification criterion.
No Q-prime calculation, bin, Jr/Ja score, or derived physical-RQD floor is used.

## Scope and boundaries

- Keep all new Python modules and tests inside the existing `src/rqd_exploration/` and
  `src/test/` trees. Do not create a new source folder.
- Extend the existing `run_rqd_exploration.py` entry surface with a clearly isolated
  raw-RQD search command while preserving all existing commands.
- Reuse validated DFN input/configuration, signature generation, execution adapter, and
  raw BH measurement components where their contracts match.
- Use only the active main domain Jn 2/4/9/15 and the current main YAML signature bounds.
- Reuse the main bounded signature proposal method, start cap, and review checkpoint.
  Run one configured realization seed per signature; do not use seed verification,
  paired-progress decisions, or a stagnation gate as a pass criterion.
- Keep each signature, realization seed, raw RQD, validity/exclusion, BH support, and
  provenance linked so that the signature-to-RQD evidence can be reconstructed.
- Require a separate schema4 database; reject existing pilot/main manifests and non-raw
  main-control runs. The database and report directory are explicit run arguments.
- Do not start a simulation, initialize/write a database, or apply results to main without
  separate explicit user authorization.

## Evidence from the current implementation

- `src/rqd_exploration/adapter.py` maps validated joint-set signature inputs to a DFN
  generation case. Its placeholder Jr/Ja values are generation-only and must not become
  analysis inputs.
- `src/rqd_exploration/measurement.py` produces raw BH RQD, validity, support, and
  measurement evidence.
- `src/rqd_exploration/runner.py` contains a one-realization generate-and-measure boundary.
- `src/rqd_exploration/design.py` provides deterministic LHS signature generation.
- `src/rqd_exploration/main_design.py` proposes bounded LHS/parameter perturbations.
  `RawRqdController` reuses that proposal engine while using Jn only as a domain condition;
  it does not use main seed-pass or paired-progress mechanics.
- `src/rqd_exploration/main_analysis.py` contains bin target intervals and a
  `physical_rqd_floor` reachability filter. The latter is not an empirically validated
  lower bound on observed RQD and must not gate raw-RQD candidates.
- `src/rqd_exploration/analysis.py` clamps calculation RQD to 10 for Q-prime scoring.
  Raw-RQD search must read `RawBHObservation.raw_rqd` directly and preserve values below 10.

## Initial raw-RQD threshold contract (superseded)

- **Domain:** active main YAML templates Jn 2/4/9/15 with their existing signature bounds.
- **Initial objective:** raw BH RQD `<= 10`, with initial seed 43 positive then 2 of
  verification seeds 44–46. This was the first implementation and is superseded by Stage 1.
- **Preserved setup:** active main YAML templates Jn 2/4/9/15, existing bounds, and
  separate database authorization.

## Current exploration contract — Stage 1 (2026-11-03)

- **Objective:** observe continuous raw BH RQD values by signature and BH location. No
  threshold defines success; RQD `<= 10` is not a pass criterion or cutoff.
- **Realization:** one run per signature using `policy.initial_seed` (currently 43). Store
  its seed for provenance only; do not schedule verification seeds 44–46.
- **Search gates:** do not use seed pass, paired-progress, or three-round stagnation logic.
  Retain the main maximum-start and review-checkpoint safeguards.
- **Refinement metric:** support-weighted mean raw RQD, alongside per-observation values,
  min/max, and support. This metric is reported now; using it to select/guide later proposals
  is Stage 2.
- **Domain/persistence:** active main Jn 2/4/9/15 and YAML bounds, with a separate database
  and explicit execution confirmation.

## Current exploration contract — Stage 2 (2026-11-03)

- **Reference ordering:** within each Jn condition, use the support-weighted mean of valid
  BH observations with at least 1 m support; lower means rank first, ties use signature ID,
  and signatures without supported measurements rank last. The existing rotating reference
  selection and bounded proposal method remain unchanged.
- **Response evidence:** each completed adaptive round stores the reference and candidate
  weighted means, candidate-minus-reference RQD delta, and changed signature-axis values
  and deltas for each joint set. Initial LHS signatures have no measured reference, so they
  do not produce an adaptive response delta.
- **Update method:** candidate changes use the existing bounded fixed-axis perturbations and
  LHS proposals. Recorded parameter/RQD deltas are observational and are not fed back as
  Euler/gradient steps.
- **No pass/fail or run:** this ranking guides proposals only. It adds no RQD cutoff,
  pass/verification rule, surrogate model, or RQD-based stop condition. The user runs the
  confirmed command; no simulation or persistent database was started here.
- **Validation:** 9 focused raw-RQD tests passed, including weighted-mean ordering and
  persisted round response deltas. `compileall` and `git diff --check` passed.

### Stage 1 implementation record (2026-11-03 19:41:41 KST +0900)

- Removed threshold target fields and threshold-based counts from the raw-RQD data model.
- Replaced the raw controller's seed-pass summaries with continuous per-signature response
  summaries: supported observation count, raw min/max, and support-weighted mean.
- Each signature queues only `policy.initial_seed` (43 in the current config). No
  verification seeds are queued, no pass/paired-progress decisions are made, and no
  stagnation state/gate is kept by the raw controller.
- The refinement metric is published in preview/run summaries but does not yet steer
  candidate selection. That behavior belongs to Stage 2.
- Focused raw-RQD tests: 7 passed. Preview: 20 candidates across Jn 2/4/9/15 with
  `simulation_started=false` and `database_written=false`. `compileall`, Pylance
  syntax/diagnostics, and `git diff --check` passed. No persistent DB or simulation ran.

## Remaining stages

1. **Stage 3 — Relationship reporting:** expose per-signature/per-location raw RQD, support,
   summary metrics, and candidate-to-reference deltas in a reviewable report.
2. **Stage 4 — Validation:** extend in-memory tests for update direction, metric calculation,
   raw observation preservation, and absence of seed/pass/stagnation gates.
3. **Stage 5 — User execution and review:** provide the finalized command and wait for the
   user to run it; do not initialize a persistent DB or run a simulation on the user's behalf.
- **Persistence and authorization:** use a dedicated database and explicit report path.
  `raw-rqd run` performs MLX preflight first and requires `--confirm-execution` before
  opening/creating its database or beginning generation. Adding this command does not
  authorize running it.
- **Reporting boundary:** preserve the raw observations in schema4 and summarize supported
  valid BH raw-RQD count/min/max/support-weighted mean by signature together with signature inputs.
  Do not fit a statistical/surrogate model or transfer results to main automatically.

## Verification boundary

Use the existing `dlo-cq` environment for Python checks. Unit tests may validate signature
serialization, raw-BH observation extraction, deterministic candidate generation, and
reporting without invoking the DFN generator. Preview is in-memory and explicitly reports
that it did not write a database or start a simulation. Controller tests may use an in-memory
SQLite database, but must not initialize a persistent/pilot database or invoke generation.

## Implemented code path

- `run_rqd_exploration.py raw-rqd preview` emits deterministic LHS signatures across active
  main Jn values in memory and reports the continuous-RQD, single-realization contract with
  `simulation_started=false`, `database_written=false`.
- `run_rqd_exploration.py raw-rqd run --database <new-separate.sqlite> --output-dir <reports>`
  requires `--confirm-execution`; it uses a raw-target fingerprint/run prefix and refuses
  pilot/main data stores.
- `src/rqd_exploration/raw_rqd_search.py` extracts BH-only observations while preserving
  raw values, validity/exclusion, support, signature ID, and seed. Summaries expose
  per-signature raw min/max and support-weighted mean without threshold classification;
  Stage 2 ranks measured references and stores adaptive response deltas.
- Focused tests cover extraction, one-seed scheduling without verification/pass state,
  deterministic all-Jn preview, and the no-confirmation/no-database-open boundary.

The code is ready for the user's separate execution decision. No search run, persistent
database initialization, DFN generation, relationship model, or main-input transfer has
been performed.
