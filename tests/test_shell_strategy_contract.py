from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STRATEGY_PATH = REPO_ROOT / "instructions" / "shell_strategy.md"
CONFIG_PATH = REPO_ROOT / "opencode.json"

EXPECTED_INSTRUCTIONS = [
    "{env:HOME}/.config/opencode/my_opencode/AGENTS.md",
    "{env:HOME}/.config/opencode/my_opencode/instructions/shell_strategy.md",
]
MAX_UTF8_BYTES = 4_000
MAX_SPLIT_LINES = 120

# Exact lines make policy drift visible. They are a static contract, not proof of
# general LLM behavior or semantic equivalence with an older instruction.
REQUIRED_LINES = (
    "# Shell Non-Interactive Strategy (Global)",
    "## Authority and execution contract",
    "OpenCode's shell has no TTY/PTTY; commands awaiting stdin, confirmation, editors, pagers, or UIs can stall until timeout.",
    "- Follow `AGENTS.md` and user-authorized scope; these defaults never override repository, user, security, or authorization rules.",
    "- Shell processes never ask interactively; legitimate assistant clarification remains allowed when `AGENTS.md` permits it.",
    "- After each tool result, analyze it and continue immediately while work remains; stop only when complete or concretely blocked.",
    "- Pair every prohibition with an executable safe alternative.",
    "- Preserve authentication, TLS, SSH host-key checks, quoting, and secret boundaries; never bypass or invent them to avoid a prompt.",
    "- If no safe non-interactive path exists, stop the command and report the exact blocker instead of weakening controls.",
    "## Environment defaults",
    "Assume `CI=true`. The guard prefixes selected Git/GitHub commands only. These desired defaults are not global; set them as needed.",
    "## Command forms",
    "Check the installed version's `--help` before using a flag. Prefer documented non-interactive modes; quiet output does not prove prompts are disabled, and `CI=true` grants no destructive authority.",
    "### Packages",
    "- npm: `npm init -y`; verify installed-version support for `npm install --yes`.",
    "- Yarn: versions differ; Classic may use `yarn install --non-interactive`.",
    "- pnpm: use `CI=true pnpm install` with explicit lockfile policy; silent reporters affect output only.",
    "- Bun: `bun init -y` when supported.",
    "- Apt: review packages, then use `DEBIAN_FRONTEND=noninteractive apt-get install -y pkg`; review upgrades separately.",
    "- Pip: `python -m pip install --no-input pkg`.",
    "- Homebrew: `HOMEBREW_NO_AUTO_UPDATE=1 brew install pkg`.",
    "### Git",
    '- Commit explicitly: `git commit -m "msg"`.',
    "- Use `git merge --no-edit branch` and `GIT_EDITOR=true` where an editor might open.",
    "- Use non-interactive rebase, explicit add paths, and `git --no-pager ...`.",
    "- Resolve conflicts through explicit file edits; never wait for an editor or prompt.",
    "### Files, archives, and network",
    "- Prefer OpenCode file tools. Use `rm -f`, `cp -f`, `mv -f`, or `unzip -o` only for exact, reviewed, authorized targets.",
    "- Common forms: `tar xf archive.tar`, `curl -fsSL URL`, `wget -q URL`; validate inputs and destinations.",
    "- Use `ssh -o BatchMode=yes host command` and `scp -o BatchMode=yes file host:path`; retain normal host-key verification.",
    "### Containers and language runtimes",
    "- Use `docker run image`, `docker exec container command`, `docker build --progress=plain .`, or `docker compose up -d`; omit `-it`.",
    '- Run `python -c "code"`, `python script.py`, `node -e "code"`, or `node script.js`; never launch a bare REPL.',
    "## Prohibited interactive forms",
    "- Editors: `vim`, `vi`, `nano`, `emacs`, `pico`, `ed`.",
    "- Pagers/manuals: `less`, `more`, `most`, `pg`, `man`; use `--help` or non-interactive docs.",
    "- Interactive Git: `git add -p`, `git rebase -i`, or `git commit` without `-m`.",
    "- Bare REPLs and interactive shells: `python`, `node`, `ipython`, `irb`, `ghci`, `bash -i`, `zsh -i`.",
    "- TTY modes such as Docker `-it`, or an `-i`/`-p` option that requests input.",
    "## Prompt fallback order",
    "1. Use a documented native non-interactive flag or environment.",
    "2. If the answers are finite and nonsecret, provide exact stdin with `printf` or a heredoc.",
    "3. If safe and available on the platform, apply a bounded command-specific timeout; handle timeout as failure, not success.",
    "4. Otherwise stop and report the blocker.",
    "Never use unbounded `yes`, pipe secrets, disable TLS/SSH host-key checks, launch an editor/pager, or equate silence with success.",
)

REQUIRED_ENV_LINES = (
    "CI=true",
    "DEBIAN_FRONTEND=noninteractive",
    "GIT_TERMINAL_PROMPT=0",
    "GIT_EDITOR=true",
    "GIT_PAGER=cat",
    "PAGER=cat",
    "GCM_INTERACTIVE=never",
    "HOMEBREW_NO_AUTO_UPDATE=1",
    "npm_config_yes=true",
    "PIP_NO_INPUT=1",
    "YARN_ENABLE_IMMUTABLE_INSTALLS=false",
)

FORBIDDEN_PATTERNS = {
    "ssh host-key bypass": re.compile(r"StrictHostKeyChecking\s*=\s*no", re.IGNORECASE),
    "known-hosts bypass": re.compile(
        r"UserKnownHostsFile\s*=\s*/dev/null", re.IGNORECASE
    ),
    "TLS bypass flag": re.compile(r"(?:curl|wget)[^\n`]*(?:--insecure|\s-k(?:\s|$))"),
    "wget certificate bypass": re.compile(r"wget[^\n`]*--no-check-certificate"),
    "Git TLS bypass": re.compile(
        r"(?:http\.sslVerify\s*=\s*false|GIT_SSL_NO_VERIFY\s*=\s*(?:1|true))",
        re.IGNORECASE,
    ),
    "Node TLS bypass": re.compile(r"NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*0"),
    "password stdin": re.compile(
        r"(?:echo|printf)[^\n|]*(?:password|token)[^\n|]*\|", re.IGNORECASE
    ),
    "sudo password stdin": re.compile(r"sudo\s+-S(?:\s|$)"),
    "unbounded yes pipe": re.compile(r"^\s*`?yes\s*\|", re.MULTILINE),
    "unconditional force mandate": re.compile(
        r"always[^\n]*(?:yes|force)[^\n]*flags?", re.IGNORECASE
    ),
    "global auto-set claim": re.compile(r"Environment Variables \(Auto-Set\)"),
    "absolute hang claim": re.compile(
        r"will always hang|will hang indefinitely", re.IGNORECASE
    ),
    "precedence inversion": re.compile(r"rules in this file override", re.IGNORECASE),
}


def validate_strategy(text: str) -> list[str]:
    errors: list[str] = []
    lines = text.splitlines()
    encoded = text.encode("utf-8")

    if len(encoded) > MAX_UTF8_BYTES:
        errors.append(f"UTF-8 budget exceeded: {len(encoded)}")
    if len(lines) > MAX_SPLIT_LINES:
        errors.append(f"line budget exceeded: {len(lines)}")
    if not text.endswith("\n") or text.endswith("\n\n"):
        errors.append("strategy must end with exactly one newline")
    if any(line != line.rstrip() for line in lines):
        errors.append("strategy contains trailing whitespace")

    for line in (*REQUIRED_LINES, *REQUIRED_ENV_LINES):
        if line not in lines:
            errors.append(f"missing exact contract line: {line}")
    for label, pattern in FORBIDDEN_PATTERNS.items():
        if pattern.search(text):
            errors.append(f"forbidden guidance present: {label}")
    return errors


def replace_exact_line(text: str, line: str, replacement: str) -> str:
    lines = text.splitlines(keepends=True)
    indexes = [
        index for index, candidate in enumerate(lines) if candidate.rstrip("\n") == line
    ]
    if len(indexes) != 1:
        raise AssertionError(f"expected one exact line for mutation: {line}")
    suffix = "\n" if lines[indexes[0]].endswith("\n") else ""
    lines[indexes[0]] = f"{replacement}{suffix}"
    return "".join(lines)


class ShellStrategyContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.strategy = STRATEGY_PATH.read_text(encoding="utf-8")

    def test_config_uses_the_canonical_instruction_inventory(self) -> None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(EXPECTED_INSTRUCTIONS, config["instructions"])

    def test_canonical_strategy_satisfies_static_contract(self) -> None:
        self.assertEqual([], validate_strategy(self.strategy))

    def test_removing_or_negating_each_required_line_is_rejected(self) -> None:
        for line in (*REQUIRED_LINES, *REQUIRED_ENV_LINES):
            expected_error = f"missing exact contract line: {line}"
            with self.subTest(line=line, mutation="removed"):
                removed = replace_exact_line(self.strategy, line, "")
                self.assertNotEqual(self.strategy, removed)
                self.assertIn(expected_error, validate_strategy(removed))
            with self.subTest(line=line, mutation="negated"):
                negated = replace_exact_line(self.strategy, line, f"NOT {line}")
                self.assertNotEqual(self.strategy, negated)
                self.assertIn(expected_error, validate_strategy(negated))

    def test_inserting_each_forbidden_example_is_rejected(self) -> None:
        examples = {
            "ssh host-key bypass": "ssh -o StrictHostKeyChecking=no host",
            "known-hosts bypass": "ssh -o UserKnownHostsFile=/dev/null host",
            "TLS bypass flag": "curl --insecure https://example.invalid",
            "wget certificate bypass": "wget --no-check-certificate https://example.invalid",
            "Git TLS bypass": "git -c http.sslVerify=false fetch",
            "Node TLS bypass": "NODE_TLS_REJECT_UNAUTHORIZED=0 npm install",
            "password stdin": 'echo "password" | command',
            "sudo password stdin": "sudo -S command",
            "unbounded yes pipe": "yes | ./installer",
            "unconditional force mandate": "Always supply yes or force flags.",
            "global auto-set claim": "## Environment Variables (Auto-Set)",
            "absolute hang claim": "These commands will always hang.",
            "precedence inversion": "Rules in this file override other documentation.",
        }
        self.assertEqual(set(FORBIDDEN_PATTERNS), set(examples))
        for label, example in examples.items():
            with self.subTest(label=label):
                errors = validate_strategy(f"{self.strategy}{example}\n")
                self.assertIn(f"forbidden guidance present: {label}", errors)


if __name__ == "__main__":
    unittest.main()
