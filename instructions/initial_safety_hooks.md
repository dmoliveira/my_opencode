# Initial Safety Hooks

Epic 4 Task 4.2 adds three low-noise hooks focused on continuation and resilience.

## Hooks

- `continuation-reminder`
  - Input: `{ "checklist": ["item", "item"] }`
  - Trigger: at least one checklist item remains
  - Output: pending count, preview, and a reminder message

- `truncate-safety`
  - Input: `{ "text": "...", "max_lines": 220, "max_chars": 12000 }`
  - Trigger: output exceeds line/char limits
  - Output: truncated text plus warning metadata

- `error-hints`
  - Input: `{ "command": "...", "exit_code": <int>, "stderr": "...", "stdout": "..." }`
  - Trigger: non-zero exit code
  - Output: categorized remediation hint for common failures

## Categories in `error-hints`

- `command_not_found`
- `path_missing`
- `permission_denied`
- `git_context`
- `timeout`
- `generic_failure`

The implementation is intentionally deterministic and dependency-free.

Governance controls and telemetry-safe logging are documented in
`instructions/hook_governance_controls.md`.
