# Local Gateway Plugin Loader Bug

OpenCode `1.2.20` does not reliably load the repo-local gateway plugin when the plugin is configured with a local `file:` spec.

## Reproduction

Run:

```bash
python3 scripts/gateway_local_plugin_runtime_smoke.py --mode both --output json
```

This exercises two local plugin forms against a wrapped `opencode serve` instance:

- `path`: `file:{env:HOME}/.config/opencode/my_opencode/plugin/gateway-core`
- `tarball`: `file:/.../plugin/gateway-core/my_opencode-gateway-core-0.1.1.tgz`

## Observed failures

- `path` mode installs successfully, then fails to resolve the plugin module from the cache path.
- `tarball` mode fails during install because the runtime appends `@latest` to the tarball `file:` spec.
- After the tarball install failure, the runtime falls back to the repo-level path plugin from `opencode.json`, which then reproduces the same path-resolution failure.

## Evidence

Run the smoke test and inspect the artifact directory printed in the JSON output under `.opencode/runtime-plugin-smoke/`.

Key log lines to expect:

- Path mode logs a `file:/.../plugin/gateway-core@latest` install, then `Cannot find module ...node_modules/file:/.../plugin/gateway-core`.
- Tarball mode logs a `file:/...my_opencode-gateway-core-0.1.1.tgz@latest` install attempt and fails with exit code `1`.
- Tarball mode then falls back to the repo path plugin and reproduces the same `Cannot find module` resolution failure.

## Impact

- Patched gateway runtime code in this repo cannot be validated end-to-end through `opencode serve` using local plugin specs.
- Gateway audit evidence such as `gateway_runtime_bootstrap` is absent because the patched plugin never loads.

## Expected behavior

- Local `file:` directory plugins should load after install without resolving through an invalid `node_modules/file:/...` module path.
- Local `file:` tarball plugins should install exactly as specified, without appending `@latest`.
