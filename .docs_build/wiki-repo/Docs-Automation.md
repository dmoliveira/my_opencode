# Docs Automation

This repository publishes docs artifacts automatically:

- GitHub Wiki pages are synced from generated markdown.
- GitHub Pages serves the docs hub from `docs/pages/index.html`.

## Trigger
- Push to `main` affecting `README.md`, `docs/**`, or workflow files.
- Manual run via workflow dispatch.
