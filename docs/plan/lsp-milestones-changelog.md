# LSP Milestones Changelog

This document is the consolidated changelog for the LSP delivery stream in `my_opencode`.

## Timeline

| Milestone | Scope | PR | Merged At (UTC) | Merge Commit |
| --- | --- | --- | --- | --- |
| LSP command baseline | Added `/lsp` readiness/doctor/navigation/symbols/rename workflows and initial docs/tests | [#229](https://github.com/dmoliveira/my_opencode/pull/229) | 2026-02-18T11:53:31Z | `a71b1c692501d7fd47b70c297b79f2243668a6fa` |
| Protocol-first execution | Upgraded `/lsp` commands to try protocol calls first with deterministic text fallback | [#231](https://github.com/dmoliveira/my_opencode/pull/231) | 2026-02-18T12:23:23Z | `76b7087c00caa38c3a9f3356d374b2ef746b5afd` |
| `documentChanges` text edits | Added `workspaceEdit.documentChanges[*].textDocument + edits` support | [#232](https://github.com/dmoliveira/my_opencode/pull/232) | 2026-02-18T20:17:23Z | `91d26ef4c25816c31a60504cd447bc1654e19ee2` |
| Resource operation safety | Parsed resource operations (`rename/create/delete file`) and blocked apply when present | [#233](https://github.com/dmoliveira/my_opencode/pull/233) | 2026-02-18T21:06:48Z | `545f03832d75ce4e6ea39a739907f735fb215667` |
| Annotation confirmation policy | Parsed `changeAnnotations`/`annotationId` and blocked apply for confirmation-required edits | [#234](https://github.com/dmoliveira/my_opencode/pull/234) | 2026-02-18T21:14:36Z | `a29fe194b848eea8301e87b34c2a05fdc5e92942` |
| Deterministic mock protocol harness | Added mock JSON-RPC LSP fixture + integration selftest coverage | [#235](https://github.com/dmoliveira/my_opencode/pull/235) | 2026-02-18T22:08:50Z | `cb6b85e7c6fc1c3f3ff743a4cc0542bbbf04d0a8` |
| Backend observability metadata | Added `backend_details` across `/lsp` JSON outputs | [#238](https://github.com/dmoliveira/my_opencode/pull/238) | 2026-02-18T22:24:59Z | `0cd1a2c7e4f07fb2dd0ac32d1f953d1afaa29e64` |
| Dry-run diff preview | Added per-file unified diff previews in `/lsp rename` dry-run JSON output | [#239](https://github.com/dmoliveira/my_opencode/pull/239) | 2026-02-18T22:45:02Z | `ab28cbd91282303d609c6c00bdf52f5546a23af5` |
| Guarded renamefile apply | Added opt-in apply path for safe `RenameFile` operations and validation helpers | [#242](https://github.com/dmoliveira/my_opencode/pull/242) | 2026-02-18T23:39:06Z | `4832f7ded4298c8a844d0509fda5ece6e8bbd80e` |
| Diff review thresholds | Added `max_diff_files` and `max_diff_lines` blockers before `/lsp rename --apply` | [#243](https://github.com/dmoliveira/my_opencode/pull/243) | 2026-02-19T01:17:01Z | `47ee1e52569e7efe3399880c4140a69d4ea4baf4` |
| Verbose capability probing | Added `/lsp doctor --verbose` command-level capability matrix and summary reporting | [#246](https://github.com/dmoliveira/my_opencode/pull/246) | 2026-02-19T02:32:17Z | `dedbb8641f6d5454269fab2e88aa374772f8f5af` |

## Notes

- PR [#237](https://github.com/dmoliveira/my_opencode/pull/237) (initial backend details branch) was superseded by [#238](https://github.com/dmoliveira/my_opencode/pull/238) due branch freshness guard constraints during merge.
- Initial protocol hardening roadmap is complete in `docs/plan/lsp-protocol-upgrade.md`; next-wave planning now continues in `docs/plan/lsp-high-value-epics.md` (E4-E6).
