const SHELL_TOKEN = String.raw `(?:"[^"]*"|'[^']*'|[^\s;&|]+)`;
const GIT_SAFE_GLOBAL_FLAGS = String.raw `(?:\s+(?:--no-pager|-C\s+${SHELL_TOKEN}|--git-dir\s+${SHELL_TOKEN}|--work-tree\s+${SHELL_TOKEN}))*`;
const GIT_SAFE_ARGS = String.raw `(?:\s+[^;&|]+)*`;
const GIT_REQUIRED_ARGS = String.raw `(?:\s+[^;&|]+)+`;
const SAFE_ENV_PREFIX = String.raw `(?:(?:env\s+)?(?:[A-Za-z_][A-Za-z0-9_]*=${SHELL_TOKEN}\s+)*)`;
const OPTIONAL_RTK_WRAPPER = String.raw `(?:(?:[^\s;&|]*/)?rtk\s+)?`;
const PROTECTED_BRANCH_REF = String.raw `(?:main|master)`;
function protectedPattern(commandPattern) {
    return new RegExp(String.raw `^${SAFE_ENV_PREFIX}${commandPattern}$`, "i");
}
function gitProtectedPattern(subcommandPattern, argsPattern = GIT_SAFE_ARGS) {
    return protectedPattern(String.raw `${OPTIONAL_RTK_WRAPPER}(?:[^\s;&|]*/)?git${GIT_SAFE_GLOBAL_FLAGS}\s+${subcommandPattern}${argsPattern}`);
}
const ALLOWED_PROTECTED_SHELL_PATTERNS = [
    protectedPattern("pwd"),
    protectedPattern(String.raw `ls(?:\s+[^;&|]+)*`),
    gitProtectedPattern("status"),
    gitProtectedPattern("diff"),
    gitProtectedPattern("log"),
    gitProtectedPattern(String.raw `branch\s+--show-current`, ""),
    gitProtectedPattern("rev-parse", GIT_REQUIRED_ARGS),
    gitProtectedPattern(String.raw `worktree\s+list`),
    gitProtectedPattern(String.raw `worktree\s+add`, GIT_REQUIRED_ARGS),
    gitProtectedPattern("fetch", ""),
    gitProtectedPattern(String.raw `fetch\s+--prune`, ""),
    gitProtectedPattern(String.raw `pull\s+--rebase`, ""),
    gitProtectedPattern(String.raw `stash\s+push`, GIT_REQUIRED_ARGS),
    gitProtectedPattern(String.raw `stash\s+pop`, ""),
    gitProtectedPattern(String.raw `stash\s+list`),
    gitProtectedPattern(String.raw `stash\s+show`),
    gitProtectedPattern(String.raw `restore\s+--source\s+${PROTECTED_BRANCH_REF}\s+--`, GIT_REQUIRED_ARGS),
    gitProtectedPattern(String.raw `checkout\s+${PROTECTED_BRANCH_REF}\s+--`, GIT_REQUIRED_ARGS),
    protectedPattern(String.raw `${OPTIONAL_RTK_WRAPPER}gh\s+pr\s+view(?:\s+[^;&|]+)*`),
    protectedPattern(String.raw `${OPTIONAL_RTK_WRAPPER}gh\s+pr\s+checks(?:\s+[^;&|]+)*`),
    protectedPattern(String.raw `make\s+(?:help|validate|selftest|doctor|doctor-json|install-test|release-check)`),
    protectedPattern(String.raw `npm(?:\s+--prefix\s+[^;&|]+)?\s+(?:test|run\s+(?:lint|test|build))`),
    protectedPattern(String.raw `pnpm(?:\s+--dir\s+[^;&|]+)?\s+(?:test|lint|build)`),
    protectedPattern(String.raw `yarn(?:\s+--cwd\s+[^;&|]+)?\s+(?:test|lint|build)`),
    protectedPattern(String.raw `bun(?:\s+--cwd\s+[^;&|]+)?\s+(?:test|run\s+(?:lint|test|build))`),
    protectedPattern(String.raw `python3?\s+-m\s+(?:unittest|pytest|py_compile)(?:\s+[^;&|]+)*`),
    protectedPattern(String.raw `pytest(?:\s+[^;&|]+)*`),
    protectedPattern(String.raw `node\s+--test(?:\s+[^;&|]+)*`),
    protectedPattern(String.raw `pre-commit\s+run(?:\s+[^;&|]+)*`),
    protectedPattern(String.raw `eslint(?:\s+[^;&|]+)*`),
    protectedPattern(String.raw `tsc(?:\s+[^;&|]+)*`),
    protectedPattern(String.raw `ruff(?:\s+[^;&|]+)*`),
];
export function normalizeShellCommand(command) {
    return command.replace(/\s+/g, " ").trim();
}
export function hasDisallowedShellSyntax(command) {
    return /&&|\|\||;|\n|\||[<>`]|\$\(|\(|\)/.test(command);
}
function hasHardDisallowedShellSyntax(command) {
    return /\|\||\||\n|[<>`]|\$\(|\(|\)/.test(command);
}
function splitChainedCommands(command) {
    return command
        .split(/&&|;/)
        .map((segment) => normalizeShellCommand(segment))
        .filter((segment) => segment.length > 0);
}
export function isAllowedProtectedShellCommand(command) {
    if (hasHardDisallowedShellSyntax(command)) {
        return false;
    }
    const normalized = normalizeShellCommand(command);
    const commands = splitChainedCommands(normalized);
    if (commands.length === 0) {
        return false;
    }
    return commands.every((candidate) => ALLOWED_PROTECTED_SHELL_PATTERNS.some((pattern) => pattern.test(candidate)));
}
