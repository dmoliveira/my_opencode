# Execution Status Sidebar

OpenCode 1.18.18 can show a small `Execution` section in its right sidebar:

```text
Goal  <native session title>
Last  <latest deterministic milestone>
Next  <next deterministic milestone>
```

The panel is local and deterministic. It does not call a model, MCP server, or external service.

## Install

Run `./install.sh`, then restart OpenCode. The installer builds both local plugins, enables the direct gateway entrypoint, and merges the sidebar entry into `~/.config/opencode/tui.json` without replacing existing TUI settings or plugins. It replaces stale `my_opencode` managed sidebar paths and removes duplicate managed entries while retaining the first tuple's options; unrelated local plugins are left unchanged.

For a live checkout, run `./scripts/setup_local_dev_symlinks.sh`. It builds the sidebar before adding the same TUI entry.

The feature requires exactly OpenCode `1.18.18`. The sidebar disables itself with a visible warning on another version.

## Status semantics

`Goal` is the title that OpenCode already stores for the active session. The gateway persists only fixed labels for `Last` and `Next`.

Typical milestones are:

- `Files updated` → `Run validation`
- `Validation passed` → `Review changes` when the host supplies an explicit zero exit code
- `Validation completed` → `Review changes` when OpenCode reports normal tool completion without an exit code
- `Changes committed` → `Push branch`
- `Branch pushed` → `Open pull request`
- `Pull request opened` → `Review pull request`
- `Pull request merged` → `Sync main`

A non-zero explicit exit code produces the matching failure label. The panel does not parse command output, prompts, model replies, or tool output.

## Privacy and bounds

Gateway state lives at `.opencode/gateway-core.state.json` in the active project. The writer uses an owner-only `.opencode` directory (`0700`) and state file (`0600`). The sidebar rejects unsafe, symlinked, oversized, stale, or malformed state.

At most 16 recent sessions and 160 characters per stored label are retained by default. Display text is clipped to fit the TUI.

## Configuration

The global `gateway-core.config.json` enables the feature by default for this repository:

```json
{
  "executionStatus": {
    "enabled": true,
    "maxSessions": 16,
    "maxLabelChars": 80
  }
}
```

Set `executionStatus.enabled` to `false` in the global or project sidecar to turn it off, then restart OpenCode.

## Verification

Run the no-model host smoke after building the gateway plugin:

```bash
make gateway-execution-status-live-smoke
```

It starts an isolated local OpenCode server, creates a session through its local API, and verifies the private `Session ready` state. The test makes no model request.
