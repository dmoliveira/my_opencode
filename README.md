# my_opencode 🚀

Welcome to my OpenCode command center! ✨

This repo is the home base for my global OpenCode setup: a clean, portable config with quick controls for MCP tools so I can switch between focused coding and research mode in seconds. ⚡

## Why this exists 🎯

- Keep one source of truth for OpenCode config.
- Make MCP usage intentional to control token spend.
- Enable fast toggling inside OpenCode with `/mcp`.
- Keep everything easy to sync, version, and evolve.

## What is inside 📦

- `opencode.json`: Global OpenCode config (symlinked from `~/.config/opencode/opencode.json`).
- `scripts/mcp_command.py`: Backend script used by the `/mcp` command.

## MCP control in OpenCode 🧠

Use these commands directly in the OpenCode prompt:

```text
/mcp status
/mcp enable context7
/mcp disable context7
/mcp enable gh_grep
/mcp disable gh_grep
/mcp enable all
/mcp disable all
```

Happy coding! 😄
