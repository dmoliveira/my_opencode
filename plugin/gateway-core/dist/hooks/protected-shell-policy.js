const SHELL_TOKEN = String.raw `(?:"[^"]*"|'[^']*'|[^\s;&|]+)`;
const GIT_SAFE_GLOBAL_FLAGS = String.raw `(?:\s+(?:--no-pager|-C\s+${SHELL_TOKEN}|--git-dir\s+${SHELL_TOKEN}|--work-tree\s+${SHELL_TOKEN}))*`;
const GIT_SAFE_ARGS = String.raw `(?:\s+[^;&|]+)*`;
const GIT_REQUIRED_ARGS = String.raw `(?:\s+[^;&|]+)+`;
const SAFE_ENV_KEY = String.raw `(?:CI|GIT_TERMINAL_PROMPT|GIT_EDITOR|GIT_PAGER|PAGER|GCM_INTERACTIVE|OPENCODE_SESSION_ID)`;
const SAFE_ENV_PREFIX = String.raw `(?:(?:env\s+)?(?:${SAFE_ENV_KEY}=${SHELL_TOKEN}\s+)*)`;
const OPTIONAL_RTK_WRAPPER = String.raw `(?:(?:[^\s;&|]*/)?rtk\s+)?`;
const PROTECTED_BRANCH_REF = String.raw `(?:main|master)`;
const SQLITE_SAFE_FLAG = String.raw `(?:-readonly|-header|-column|-csv|-json|-line|-list)`;
const GH_PROTECTED_BINARY = String.raw `${OPTIONAL_RTK_WRAPPER}(?:[^\s;&|]*/)?gh`;
function protectedPattern(commandPattern) {
    return new RegExp(String.raw `^${SAFE_ENV_PREFIX}${commandPattern}$`, "i");
}
function gitProtectedPattern(subcommandPattern, argsPattern = GIT_SAFE_ARGS) {
    return protectedPattern(String.raw `${OPTIONAL_RTK_WRAPPER}(?:[^\s;&|]*/)?git${GIT_SAFE_GLOBAL_FLAGS}\s+${subcommandPattern}${argsPattern}`);
}
function sqliteProtectedPattern() {
    return protectedPattern(String.raw `(?:[^\s;&|]*/)?sqlite3(?=[^;&|]*\s-readonly\b)(?:\s+${SQLITE_SAFE_FLAG})*\s+${SHELL_TOKEN}\s+(?:(?:"\.(?:tables|schema(?:\s+[^"]+)?)")|(?:'\.(?:tables|schema(?:\s+[^']+)?)')|(?:"PRAGMA\s+table_info\s*\([^";=]+\)\s*;?")|(?:'PRAGMA\s+table_info\s*\([^';=]+\)\s*;?')|(?:"SELECT\b[^";]*;?")|(?:'SELECT\b[^';]*;?'))`);
}
const ALLOWED_PROTECTED_SHELL_PATTERNS = [
    protectedPattern("pwd"),
    protectedPattern(String.raw `ls(?:\s+[^;&|]+)*`),
    gitProtectedPattern("status"),
    gitProtectedPattern("diff"),
    gitProtectedPattern("log"),
    gitProtectedPattern(String.raw `branch\s+--show-current`, ""),
    gitProtectedPattern(String.raw `branch\s+(?:-d|--delete)`, GIT_REQUIRED_ARGS),
    gitProtectedPattern("rev-parse", GIT_REQUIRED_ARGS),
    gitProtectedPattern(String.raw `worktree\s+list`),
    gitProtectedPattern(String.raw `worktree\s+add`, GIT_REQUIRED_ARGS),
    gitProtectedPattern(String.raw `worktree\s+remove`, GIT_REQUIRED_ARGS),
    gitProtectedPattern("fetch", ""),
    gitProtectedPattern(String.raw `fetch\s+--prune`, ""),
    gitProtectedPattern(String.raw `pull\s+--rebase`, ""),
    gitProtectedPattern(String.raw `stash\s+push`, GIT_REQUIRED_ARGS),
    gitProtectedPattern(String.raw `stash\s+pop`, ""),
    gitProtectedPattern(String.raw `stash\s+list`),
    gitProtectedPattern(String.raw `stash\s+show`),
    gitProtectedPattern(String.raw `restore\s+--source\s+${PROTECTED_BRANCH_REF}\s+--`, GIT_REQUIRED_ARGS),
    gitProtectedPattern(String.raw `checkout\s+${PROTECTED_BRANCH_REF}\s+--`, GIT_REQUIRED_ARGS),
    protectedPattern(String.raw `${GH_PROTECTED_BINARY}\s+pr\s+view(?:\s+[^;&|]+)*`),
    protectedPattern(String.raw `${GH_PROTECTED_BINARY}\s+pr\s+checks(?:\s+[^;&|]+)*`),
    sqliteProtectedPattern(),
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
function forEachUnquotedCharacter(command, visitor) {
    let quote = null;
    for (let index = 0; index < command.length; index += 1) {
        const char = command[index] ?? "";
        if (quote) {
            if (char === quote) {
                quote = null;
            }
            else if (char === "\\" && quote === '"' && index + 1 < command.length) {
                index += 1;
            }
            continue;
        }
        if (char === '"' || char === "'") {
            quote = char;
            continue;
        }
        if (visitor(char, index, command) === true) {
            return true;
        }
    }
    return false;
}
export function hasDisallowedShellSyntax(command) {
    return forEachUnquotedCharacter(command, (char, index, value) => {
        if (char === "&" && value[index + 1] === "&") {
            return true;
        }
        if (char === "|" && value[index + 1] === "|") {
            return true;
        }
        if (char === ";" || char === "\n" || char === "|" || char === "<" || char === ">" || char === "`" || char === "(" || char === ")") {
            return true;
        }
        if (char === "$" && value[index + 1] === "(") {
            return true;
        }
        return false;
    });
}
function hasHardDisallowedShellSyntax(command) {
    return forEachUnquotedCharacter(command, (char, index, value) => {
        if (char === "|" && value[index + 1] === "|") {
            return true;
        }
        if (char === "|" || char === "\n" || char === "<" || char === ">" || char === "`" || char === "(" || char === ")") {
            return true;
        }
        if (char === "$" && value[index + 1] === "(") {
            return true;
        }
        return false;
    });
}
function hasShellExpansionSyntax(command) {
    return /`|\$\(|\$\{|\$[A-Za-z_]/.test(command);
}
function splitChainedCommands(command) {
    const segments = [];
    let current = "";
    let quote = null;
    for (let index = 0; index < command.length; index += 1) {
        const char = command[index] ?? "";
        if (quote) {
            current += char;
            if (char === quote) {
                quote = null;
            }
            else if (char === "\\" && quote === '"' && index + 1 < command.length) {
                current += command[index + 1] ?? "";
                index += 1;
            }
            continue;
        }
        if (char === '"' || char === "'") {
            quote = char;
            current += char;
            continue;
        }
        if (char === ";") {
            const normalized = normalizeShellCommand(current);
            if (normalized) {
                segments.push(normalized);
            }
            current = "";
            continue;
        }
        if (char === "&" && command[index + 1] === "&") {
            const normalized = normalizeShellCommand(current);
            if (normalized) {
                segments.push(normalized);
            }
            current = "";
            index += 1;
            continue;
        }
        current += char;
    }
    const normalized = normalizeShellCommand(current);
    if (normalized) {
        segments.push(normalized);
    }
    return segments;
}
export function isAllowedProtectedShellCommand(command) {
    if (hasHardDisallowedShellSyntax(command) || hasShellExpansionSyntax(command)) {
        return false;
    }
    const normalized = normalizeShellCommand(command);
    const commands = splitChainedCommands(normalized);
    if (commands.length === 0) {
        return false;
    }
    return commands.every((candidate) => ALLOWED_PROTECTED_SHELL_PATTERNS.some((pattern) => pattern.test(candidate)));
}
