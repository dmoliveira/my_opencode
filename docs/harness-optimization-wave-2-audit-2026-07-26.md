# Harness optimization audit — wave 2

## Scope

This high-risk wave hardens provider-boundary secret handling, reduces measured transform dispatch overhead, and pins the existing disabled browser integration before realistic model-backed validation. Review budget: 3–5 changed-evidence review-and-fix passes.

## Provider-boundary security

- The secret-pattern compiler now supports leading JavaScript-compatible `(?i)`, `(?m)`, and `(?s)` flags and rejects malformed patterns without logging pattern text.
- A bounded finalizer redacts mutable message and system content after configurable hooks and blocks immutable, unknown, cyclic, or exhausted traversals when a configured secret pattern could escape.
- Nested structured tool output, shared references, true cycles, traversal limits, generic-hook disablement, and explicit provider-boundary opt-out have regression coverage.
- The isolated localhost transport captured one provider request with control markers present, synthetic canaries absent, a redaction token and safe audit event present, no forwarded host-sensitive environment keys, and only header names plus expected fake authorization presence retained. Isolated local runtime persistence remained observable and is not claimed as scrubbed.

## Transform dispatch benchmark

The fixed tracked fixtures are:

- `scripts/fixtures/harness-wave2-dispatch-transform.mjs`
- `scripts/fixtures/harness-wave2-dispatch-config.json`

The byte-identical runtime copies had SHA-256 values `1b02b6a6f10e93299c12e193de94518bd137570b978b80123e1ea7b1b2769690` and `af01a8020cb728aa247e05db052a85d326204515d1206dbdb891fa147af6259e`, respectively. The before measurement used source and generated dist from commit `efd0f91ae4def9ec2cfd5ace346d2c6a56b058ca`.

Normalized command:

```bash
env -i CI=true PATH=<system> HOME=<isolated> XDG_CONFIG_HOME=<isolated> \
  MY_OPENCODE_GATEWAY_CONFIG_PATH=scripts/fixtures/harness-wave2-dispatch-config.json \
  MY_OPENCODE_GATEWAY_EVENT_AUDIT=1 \
  MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH=<artifact>.jsonl \
  MY_OPENCODE_GATEWAY_DISPATCH_SAMPLE_RATE=1 \
  WAVE2_DISPATCH_PROJECT=<isolated> \
  node scripts/fixtures/harness-wave2-dispatch-transform.mjs
```

| Phase | Total hooks | Selected hooks | Actual loop attempts | Reduction |
| --- | ---: | ---: | ---: | ---: |
| Before task 3 | 86 | 86 | 86 | — |
| Task 3 candidate | 85 | 73 | 73 | 13 (15.1%) |

The fixture and config hashes were unchanged between measurements. The candidate source and generated-dist SHA-256 values were `1351c73168923ca07fbe4e8491ff9b6611769d6746f5c9e008681d1fc2568262` and `e8e08e3c6cf916e360746b3fce9222d848c07118da1d741ca6f440bcef244c26`. This exceeds the required reduction of 12 attempts. A repeated isolated localhost provider capture passed after routing changed.

## Browser and model-backed evidence

Pending task 4.
