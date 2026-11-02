---
status: blocked
priority: medium
updated: 2026-11-03
---

# Local Data Lifecycle — Task 26

Depth: medium; risk: medium for the offline slice. Destructive source apply is
not part of the implemented capability and remains blocked, not silently complete.

## Slice 1: Offline Workflow And Counts-Only Summary

Implemented and validated as the first delivery slice. The task remains open for
source-removal/redaction capabilities; no actual source changes were performed.

- Strict owner-specific request schemas for all four stores.
- Safe private bounded JSON reader; content-free failures and summary.
- No source discovery, subprocess, network, output file, apply or deletion.
- Native inspection/export/archive-preview guidance only; source counts,
  authorization, quiescence and recovery always explicitly unverified.
- Operator workflow and mutation-capability blocker documented in
  `docs/local-data-lifecycle.md`.

## Validation

- Adversarial input/selector/privacy/filesystem/resource-boundary tests.
- Actual isolated CLI runs: all sentinel stores and sidecars byte-identical,
  no new files, no leaked canaries on stdout/stderr.
- Full `make validate` with Python 3.12, scoped Ruff, configured pre-commit,
  diff check and two changed-diff review/fix passes.

Evidence: 638 Python tests run (one skipped), all configured pre-commit hooks and
scoped Ruff passed. Two changed-diff reviews repaired native scope validation,
private path-expansion error handling and reader-guarantee documentation; final
review found no blockers in this offline slice. Isolated actual CLI tests assert
no new files or changed store/sidecar bytes and no privacy canaries on stdout/stderr.

## Next Slice / Blocker

Define owner-specific atomic preview/inventory and quiescence guarantees before
source removal/redaction. Runtime deletion cascades descendants without a discovered
revision-bound preview; sidecar per-session artifact ownership is not enumerable
from the index alone. Cross-store partial-failure/retry semantics remain unresolved.
Do not write direct SQLite mutations or broad directory removal to work around this.
