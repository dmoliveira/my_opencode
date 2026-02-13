# Browser Automation Profile Model

Epic 13 Task 13.1 defines the provider profile contract for browser automation.

## Goals

- support a stable default browser automation path while keeping provider switching reversible
- keep profile selection explicit and inspectable in config, status, and doctor flows
- make migration from older installs deterministic and low-risk

## Supported providers

- `playwright`: default stable provider for most users
- `agent-browser`: optional provider for users who need agent-browser specific workflows

Provider ids are lowercase and validated strictly. Unknown provider ids must fail with actionable guidance.

## Profile shape

Reference config shape:

```json
{
  "browser": {
    "provider": "playwright",
    "providers": {
      "playwright": {
        "enabled": true,
        "command": "npx",
        "args": ["@playwright/mcp@latest"],
        "doctor": {
          "required_binaries": ["node", "npx"],
          "install_hint": "npm i -D @playwright/mcp"
        }
      },
      "agent-browser": {
        "enabled": false,
        "command": "agent-browser",
        "args": [],
        "doctor": {
          "required_binaries": ["agent-browser"],
          "install_hint": "install agent-browser CLI and authenticate"
        }
      }
    }
  }
}
```

## Defaults

- default selected provider: `playwright`
- default enablement: selected provider enabled, non-selected provider disabled
- default failure mode: if selected provider dependencies are missing, keep selection but report exact install fixes

## Migration behavior

When existing installs do not have a `browser` section:

1. create `browser.provider = "playwright"`
2. scaffold both provider entries with deterministic defaults
3. preserve unrelated config sections without mutation

When legacy browser-related keys are found:

- map known legacy keys to the new provider shape
- keep unknown legacy keys untouched
- emit a migration note in status/doctor output so users can verify effective settings

## Validation requirements

- `provider` must exist in `providers`
- only one provider can be effectively enabled at a time
- selected provider command must be non-empty
- doctor metadata must include at least one install hint for missing dependency states

## Integration targets

- Task 13.2 should implement command backend and provider doctor checks from this schema
- Task 13.3 should add wizard integration and user-facing docs for provider trade-offs
- Task 13.4 should verify switching, persistence, and install smoke behavior
