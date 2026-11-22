# OpenCode Integration Audit Refresh

Status: implementation validated; delivery and post-merge runtime sync remain.

## Objective

Apply the audit's independently safe version and hook-tooling updates without
claiming or enabling unsupported OpenCode V2 gateway protections.

## Slices

1. Refresh GitHub Actions, pre-commit hook-repository, and disabled Playwright
   MCP pins to current supported releases.
2. Update gateway-core build dependencies and lockfile within declared
   compatibility ranges; remediate vulnerabilities without forced major jumps.
3. Refresh the experimental V2 sidebar's SDK/UI dependencies and qualify both
   its known 2.2.6 baseline and current 2.3.2 release in isolated live tests.
   Keep the sidebar unconfigured until the existing V2 activation gates pass.
4. Apply only non-breaking fixes to the legacy V1 sidebar dependency tree. Do
   not remove V1 support or replace its TUI API as part of this maintenance
   slice; unresolved major-version advisories remain tracked as a migration
   blocker.
5. Enable the deterministic standalone helper hooks and install the configured
   Git pre-commit hook locally after the repository changes validate.
6. After PR merge, synchronize the clean global runtime worktree to current
   `main` so its model/provider configuration is no longer two commits behind.

## Explicit blockers and safety boundaries

- The configured gateway is still a V1 plugin and OpenCode V2 does not load its
  security hooks. The measured shell-admission gap requires a host-level fix;
  plugin changes alone do not establish enforcement. Keep gateway protection
  and the experimental sidebar unconfigured until the migration task's
  controlled-provider and host-boundary gates pass.
- Do not upgrade or restart the active OpenCode service merely to chase the
  latest CLI. The migration evidence currently covers 2.2.5/2.2.6, while newer
  releases change plugin and shell lifecycle behavior. Qualify a newer CLI in
  isolated tests first.
- V1 sidebar advisories require incompatible API/package major changes for a
  full audit fix. Preserve its legacy support and only accept lockfile changes
  that pass its existing tests.
- The latest compatible V1 lockfile refresh removes the fixable brace-expansion
  advisory. Its remaining 12 npm audit findings (including four critical
  findings) require API-breaking `@opencode-ai/plugin` / OpenTUI major updates.
  The latest V2 dependency refresh fixes the compatible SolidJS advisory and
  all currently fixable transitive findings; 23 moderate findings remain with
  `fixAvailable: false` in the current upstream SDK/UI dependency tree.
- The separate runtime worktree is clean but behind `origin/main`; sync it only
  after the delivery branch is merged and after a fresh status check.

## Qualification results

- Playwright MCP `0.0.86` passes package provenance and the exact 71-tool
  inventory, retaining all six configured capabilities. Its OpenCode MCP
  entry remains disabled.
- The experimental V2 sidebar typechecks and passes unit/live tests on both
  OpenCode `2.2.6` and `2.3.2`; this qualifies only the sidebar surface, not
  gateway security or CLI migration.
- `gateway-core` npm audit is clean after semver-compatible dependency refresh.
- The full `make validate`, `make selftest`, and `make install-test` checks pass
  with Python 3.12 and the approved `/private/var/.../T/opencode` temp root.
  Plugin tests and docs automation checks pass as well.

## Validation

- `git diff --check`
- `npm --prefix plugin/gateway-core run lint`
- `npm --prefix plugin/gateway-core run test`
- `npm --prefix plugin/gateway-sidebar test`
- `npm --prefix plugin/gateway-sidebar-v2 run typecheck`
- `npm --prefix plugin/gateway-sidebar-v2 test`
- V2 sidebar live smoke on the retained 2.2.6 target and current 2.3.2 target,
  using isolated runtime homes.
- `npm audit` in each plugin package; explain any findings that require a
  breaking API or are not fixable from the current release.
- `make validate`, `make selftest`, `make install-test`, and
  `pre-commit run --all-files`.
- Verify actual MCP status, local hook status, gateway fail-closed status, PR
  checks, and the post-merge global runtime branch/status.
