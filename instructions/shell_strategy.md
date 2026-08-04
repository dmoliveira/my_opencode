# Shell Non-Interactive Strategy (Global)

## Authority and execution contract

OpenCode's shell has no TTY/PTTY; commands awaiting stdin, confirmation, editors, pagers, or UIs can stall until timeout.

- Follow `AGENTS.md` and user-authorized scope; these defaults never override repository, user, security, or authorization rules.
- Shell processes never ask interactively; legitimate assistant clarification remains allowed when `AGENTS.md` permits it.
- After each tool result, analyze it and continue immediately while work remains; stop only when complete or concretely blocked.
- Pair every prohibition with an executable safe alternative.
- Preserve authentication, TLS, SSH host-key checks, quoting, and secret boundaries; never bypass or invent them to avoid a prompt.
- If no safe non-interactive path exists, stop the command and report the exact blocker instead of weakening controls.

## Environment defaults

Assume `CI=true`. The guard prefixes selected Git/GitHub commands only. These desired defaults are not global; set them as needed.

```text
CI=true
DEBIAN_FRONTEND=noninteractive
GIT_TERMINAL_PROMPT=0
GIT_EDITOR=true
GIT_PAGER=cat
PAGER=cat
GCM_INTERACTIVE=never
HOMEBREW_NO_AUTO_UPDATE=1
npm_config_yes=true
PIP_NO_INPUT=1
YARN_ENABLE_IMMUTABLE_INSTALLS=false
```

## Command forms

Check the installed version's `--help` before using a flag. Prefer documented non-interactive modes; quiet output does not prove prompts are disabled, and `CI=true` grants no destructive authority.

### Packages

- npm: `npm init -y`; verify installed-version support for `npm install --yes`.
- Yarn: versions differ; Classic may use `yarn install --non-interactive`.
- pnpm: use `CI=true pnpm install` with explicit lockfile policy; silent reporters affect output only.
- Bun: `bun init -y` when supported.
- Apt: review packages, then use `DEBIAN_FRONTEND=noninteractive apt-get install -y pkg`; review upgrades separately.
- Pip: `python -m pip install --no-input pkg`.
- Homebrew: `HOMEBREW_NO_AUTO_UPDATE=1 brew install pkg`.

### Git

- Commit explicitly: `git commit -m "msg"`.
- Use `git merge --no-edit branch` and `GIT_EDITOR=true` where an editor might open.
- Use non-interactive rebase, explicit add paths, and `git --no-pager ...`.
- Resolve conflicts through explicit file edits; never wait for an editor or prompt.

### Files, archives, and network

- Prefer OpenCode file tools. Use `rm -f`, `cp -f`, `mv -f`, or `unzip -o` only for exact, reviewed, authorized targets.
- Common forms: `tar xf archive.tar`, `curl -fsSL URL`, `wget -q URL`; validate inputs and destinations.
- Use `ssh -o BatchMode=yes host command` and `scp -o BatchMode=yes file host:path`; retain normal host-key verification.

### Containers and language runtimes

- Use `docker run image`, `docker exec container command`, `docker build --progress=plain .`, or `docker compose up -d`; omit `-it`.
- Run `python -c "code"`, `python script.py`, `node -e "code"`, or `node script.js`; never launch a bare REPL.

## Prohibited interactive forms

- Editors: `vim`, `vi`, `nano`, `emacs`, `pico`, `ed`.
- Pagers/manuals: `less`, `more`, `most`, `pg`, `man`; use `--help` or non-interactive docs.
- Interactive Git: `git add -p`, `git rebase -i`, or `git commit` without `-m`.
- Bare REPLs and interactive shells: `python`, `node`, `ipython`, `irb`, `ghci`, `bash -i`, `zsh -i`.
- TTY modes such as Docker `-it`, or an `-i`/`-p` option that requests input.

## Prompt fallback order

1. Use a documented native non-interactive flag or environment.
2. If the answers are finite and nonsecret, provide exact stdin with `printf` or a heredoc.
3. If safe and available on the platform, apply a bounded command-specific timeout; handle timeout as failure, not success.
4. Otherwise stop and report the blocker.

Never use unbounded `yes`, pipe secrets, disable TLS/SSH host-key checks, launch an editor/pager, or equate silence with success.
