# QSimEx Project Instructions

For QSimEx work, follow [the detailed coding and collaboration guidelines](SKILL.md).

## Required workflow

- Before work or resuming, read the current status and latest relevant entries in `Specification/ImplementationPlan_v4.md` and `Specification/RQDExplorationStrategy_20261026/plan.md`; inspect referenced checkpoints, code, and tests as needed. Reconcile older notes against newer timestamped records; do not repeat completed tasks.
- The strategy plan's latest timestamped user agreement controls scientific meaning and approval. The implementation plan controls task order, dependencies, and verification. Record and resolve conflicts; never silently guess.
- Work only on the requested/approved step. At completion, report changes, actual verification, limitations/unrun actions, and propose the next step. Wait for the user's instruction before starting it.
- Record significant agreements, decisions, completion, interruption, and handoff in the relevant plan/checkpoint with a timezone-aware timestamp. Keep historical records and clearly identify the latest current status. Synchronize affected status/checklists in both plans.
- Ask before choices that affect scientific meaning, behavior, data contracts, scope, or execution approval. Do not treat recommendations as approval.
- Separate code/tests and in-memory previews or preflight from persistent pilot actions. Implementing storage code does not authorize initializing a pilot DB, persisting a real manifest, generating DFNs, or running simulations. Each such real execution requires explicit user authorization.
- Preserve existing work and conventions. Make focused changes, add/run relevant tests, check the diff, and report only checks actually performed.
