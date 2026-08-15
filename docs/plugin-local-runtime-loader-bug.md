# Local Gateway Plugin Loader

OpenCode `1.18.18` loads the local gateway reliably when configuration targets the built module directly:

```json
{
  "plugin": [
    "file://{env:HOME}/.config/opencode/my_opencode/plugin/gateway-core/dist/index.js"
  ]
}
```

Do not configure the package directory (`file:{env:HOME}/.../plugin/gateway-core`). OpenCode's directory-package resolver can install or cache that form without dispatching the plugin at runtime. The direct `dist/index.js` URI bypasses that resolver.

## Validation

The deterministic loader contract stays network-free:

```bash
python3 scripts/gateway_local_plugin_runtime_smoke.py --mode contract --output json
```

For an actual server lifecycle check without a model request, run:

```bash
make gateway-execution-status-live-smoke
```

The live smoke starts an isolated local server, creates one session through the local API, and requires the gateway to write a private `Session ready` entry. It does not reuse host configuration, send a prompt, or make a model request.

## Migration

`/gateway enable` recognizes the old directory form, replaces it with one direct built-entrypoint spec, and preserves options from the first matching tuple. `/gateway disable` removes both forms. Older `gateway-core@latest` compatibility aliases can remain on disk; they are no longer used by the direct entrypoint.
