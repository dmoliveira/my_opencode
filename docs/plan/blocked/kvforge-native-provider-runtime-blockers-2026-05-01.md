# KVForge native provider runtime blockers

Date: 2026-05-01

## Summary

Native KVForge custom-provider routing works in the sandbox, but validation is currently blocked by two upstream/runtime issues:

1. successful KVForge build sessions complete without persisting an assistant `text` part in the runtime DB
2. large stock OpenCode-shaped KVForge requests can still hit vLLM with `max_tokens=32000` and later fail with `EngineDeadError` / `execute_model` timeout

## Repro

1. Configure sandbox OpenCode root config with native `provider.kvforge` and active model `kvforge/gpt-5.4-fast`.
2. Configure gateway sidecar `llmDecisionRuntime.model` to `kvforge/gpt-5.4-fast`.
3. Run a sandbox build session through OpenCode using the native custom-provider path.
4. Inspect the sandbox SQLite DB at `/tmp/kvforge-live-picker-check/home/.local/share/opencode/opencode.db`.
5. Compare with a baseline local OpenAI build session in the operator runtime DB at `~/.local/share/opencode/opencode.db`.
6. Inspect live KVForge logs at `/Users/diego/.kvforge/logs/server-current.log` for the large-request failure case.

## Expected

- successful KVForge build sessions should persist assistant `text` parts the same way baseline OpenAI build sessions do
- oversized requests should be clamped or rejected safely before destabilizing the backing model engine

## Actual

- sandbox config correctly writes native KVForge provider/model entries and routing reaches KVForge
- successful KVForge build session `ses_21cbdb8d9ffeqmlirHipvBTlYI` stores an assistant message with `completed` time and output tokens but only `step-start` / `step-finish` parts
- baseline OpenAI build session `ses_21f996148ffe77v4AJGNoc7yT6` stores `step-start`, `reasoning`, `text`, and `step-finish`
- large stock OpenCode-shaped KVForge requests still appear in logs with `max_tokens=32000` and can later fail with `EngineDeadError` / `RPC call to execute_model timed out`

## Evidence

### Sandbox config

- `/tmp/kvforge-live-picker-check/home/.config/opencode/opencode.json`
  - `provider.kvforge.options.baseURL = http://127.0.0.1:18120/v1`
  - `provider.kvforge.models.gpt-5.4-fast.limit.context = 65536`
  - `provider.kvforge.models.gpt-5.4-fast.limit.output = 64512`
  - `model = kvforge/gpt-5.4-fast`
- `/tmp/kvforge-live-picker-check/home/.config/opencode/gateway-core.config.json`
  - `llmDecisionRuntime.model = kvforge/gpt-5.4-fast`

### Successful KVForge session with missing assistant text part

- session: `ses_21cbdb8d9ffeqmlirHipvBTlYI`
- assistant message row:
  - `providerID = kvforge`
  - `modelID = gpt-5.4-fast`
  - `tokens.output = 6`
  - `time.completed = 1777634325802`
- assistant parts:
  - `{"type":"step-start"}`
  - `{"type":"step-finish","reason":"stop",...}`
- no assistant `{"type":"text",...}` part exists for the completed assistant message

### Baseline OpenAI build session with expected assistant text persistence

- session: `ses_21f996148ffe77v4AJGNoc7yT6`
- assistant message row:
  - `providerID = openai`
  - `mode = build`
  - `finish = stop`
- assistant parts include:
  - `{"type":"step-start"}`
  - `{"type":"reasoning",...}`
  - `{"type":"text",...}`
  - `{"type":"step-finish","reason":"stop",...}`

### Large-request instability

- `/Users/diego/.kvforge/logs/server-current.log`
  - engine initialized with `max_model_len = 65536`
  - later fatal path shows `EngineCore encountered a fatal error`
  - terminal error includes `TimeoutError: RPC call to execute_model timed out`
  - API server reports `EngineDeadError: EngineCore encountered an issue`
- `/tmp/kvforge-live-picker-check/home/.local/share/opencode/log/*.log`
  - logs show `providerID=kvforge`
  - large request payloads still show `requestBodyValues.max_tokens=32000`

## Scope split

### 1. Runtime persistence gap

Likely upstream/runtime session persistence or provider-response mapping issue.

Why this is separate:

- routing works
- successful assistant message completes
- tokens are recorded
- only assistant text persistence is missing

### 2. Large-request model/runtime instability

Likely separate KVForge/vLLM runtime stability issue under stock OpenCode request shape.

Why this is separate:

- direct smaller streaming requests can succeed
- native provider routing works before the crash
- fatal failure occurs later in model execution with `EngineDeadError` / `execute_model` timeout

## Current repo-local status

- in-repo native-provider config/discovery work is implemented in this branch
- gateway clamp tests pass locally:
  - `node --test plugin/gateway-core/test/context-limit.test.mjs plugin/gateway-core/test/chat-params-clamp.test.mjs`
- end-to-end patched local-plugin runtime validation is still limited by the separate loader issue documented in `docs/plugin-local-runtime-loader-bug.md`

## Recommended upstream report text

Use the bug report draft prepared from this evidence set and split the report into two linked issues:

1. completed native custom-provider sessions missing assistant text persistence
2. large OpenCode-shaped local-model requests destabilizing vLLM despite native provider routing succeeding
