---
name: qsimex-coding-guidelines
description: "Apply when changing, reviewing, debugging, or testing QSimEx code. Prioritize requirement fidelity, minimal changes, scientific correctness, and verified results."
---

# QSimEx Coding and Collaboration Guidelines

Practical project guidance adapted from widely used coding principles and the
QSimEx implementation conventions. These guidelines complement the approved
strategy, implementation plan, tests, and workspace instructions—not replace them.

## 1. Resume from the authoritative project state

- Before starting or resuming, read the latest relevant entries in
  `Specification/RQDExplorationStrategy_20261026/plan.md` and
  `Specification/ImplementationPlan_v4.md`, plus referenced checkpoints when
  present. Inspect the affected code and tests.
- Treat the strategy plan's latest timestamped user agreement as authoritative
  for scientific meaning and approvals; use the implementation plan for task
  order, dependencies, and verification.
- Reconcile older handoff notes against later timestamped results. Do not repeat
  completed work or treat an older resume note as the current state.
- Identify the task's acceptance conditions and smallest relevant verification
  before editing.

## 2. Work only within the authorized step

- Execute the requested step only. A suggested next step is not authorization:
  after reporting a step's outcome and proposing what comes next, wait for the
  user's instruction before starting it.
- Ask before proceeding when an unresolved choice could change behavior,
  scientific meaning, data contracts, approval boundaries, or scope. Do not
  turn a recommendation into an assumed decision.
- Make focused, complete changes at the source. Reuse existing APIs and
  patterns; avoid duplicate calculations, speculative abstractions, and
  unrelated cleanup.
- Preserve public interfaces, numerical conventions, units, fingerprint
  semantics, and legacy Euler behavior unless a change is approved.
- Keep errors visible; do not hide failures behind silent defaults, broad
  exception handling, or success-shaped fallbacks. Preserve unrelated work and
  do not modify archived `obsolete/` material.

## 3. Keep implementation, preview, and real execution separate

- Do not infer or alter research policies, thresholds, geometry, sampling rules,
  measurement conventions, version identifiers, or data contracts without
  documented approval.
- Keep raw measurements separate from derived scores and planned support.
- Code and tests for storage may be implemented when the task authorizes them.
  This does not authorize creating/initializing a pilot database, persisting a
  real manifest, generating DFNs, or running a pilot/simulation.
- Require explicit user authorization for each real-data/pilot execution
  boundary. A test fixture, in-memory preview, or hardware/runtime preflight is
  not a database write, DFN generation, or simulation.
- If implementation conflicts with the approved strategy or plan, stop at that
  boundary, record the discrepancy, and request a decision.

## 4. Record decisions and keep the current state clear

- Record important user agreements, decisions, completed steps, interruptions,
  and handoffs in the relevant plan/checkpoint without waiting for a reminder.
  Include a timezone-aware local timestamp (`YYYY-MM-DD HH:MM +09:00`).
- Preserve historical entries. Add a clearly dated current-state summary so
  older handoffs cannot be mistaken for the latest status.
- When a step changes status, synchronize the relevant task checkboxes and
  status summaries across the strategy plan and implementation plan. Record
  code completion separately from documentation changes, DB persistence, and
  pilot execution.

## 5. Verify, then hand off

- Add or update focused tests for changed behavior; run the narrowest relevant
  tests and required regressions.
- Check the final diff and relevant diagnostics. Report the commands and actual
  results. Distinguish tests, preflight checks, in-memory previews, persistent
  writes, DFN generation, and simulation.
- Pilot execution must report observable phases and periodic heartbeats, not
  only job boundaries. Keep progress instrumentation behavior-neutral and state
  what its counters do and do not measure.
- Do not mark work complete when a required check failed or was not run.
- At each handoff, state what changed, verification results, limitations or
  unrun actions, and the next dependency/decision. Then wait for the user's
  instruction; do not continue into that next step.

## 6. Python environment

- Run Python commands, tests, and dependency checks only in the existing conda
  `dlo-cq` environment. Use `conda run -n dlo-cq ...` for tests and checks. For
  an interactive pilot run where the user needs live terminal progress, first
  activate `dlo-cq` and invoke `python -u ...` directly so no `conda run` wrapper
  captures output.
- Do not use or create `.venv` or another Python environment. The parent
  directory's `.venv` was removed on 2026-10-30 at the user's request and must
  not be recreated.

## Application

The always-on `.github/copilot-instructions.md` directs QSimEx work to follow
this document. Keep the concise approval and handoff rules in that instruction
file; maintain the detailed workflow here.
