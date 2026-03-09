import { readFileSync } from "node:fs";
import { resolve } from "node:path";
const COMMAND_SEPARATOR_TOKENS = new Set(["&&", "||", ";", "|"]);
const FIELD_FLAGS = new Set(["-f", "-F", "--field", "--raw-field"]);
const VALUE_FLAGS = new Set(["-X", "--method", "--input", "-H", "--header", "--hostname"]);
export function tokenizeShellCommand(command) {
    const matches = command.match(/"[^"]*"|'[^']*'|\S+/g);
    if (!matches) {
        return [];
    }
    return matches.map((token) => {
        if (token.length >= 2 && ((token.startsWith('"') && token.endsWith('"')) || (token.startsWith("'") && token.endsWith("'")))) {
            return token.slice(1, -1);
        }
        return token;
    });
}
function isGhBinary(token) {
    return /(?:^|[\/])gh(?:\.exe)?$/i.test(token);
}
function commandTokens(tokens, startIndex) {
    const command = [];
    for (let index = startIndex; index < tokens.length; index += 1) {
        const token = tokens[index];
        if (COMMAND_SEPARATOR_TOKENS.has(token)) {
            break;
        }
        command.push(token);
    }
    return command;
}
function inlineOptionValue(token, name) {
    if (token.startsWith(`${name}=`)) {
        return token.slice(name.length + 1);
    }
    if (name.length === 2 && token.startsWith(name) && token.length > name.length) {
        return token.slice(name.length);
    }
    return "";
}
function parseFieldAssignment(token) {
    const equalsIndex = token.indexOf("=");
    if (equalsIndex <= 0) {
        return null;
    }
    return {
        key: token.slice(0, equalsIndex).trim().toLowerCase(),
        value: token.slice(equalsIndex + 1),
    };
}
function readBodyFromInputFile(directory, filePath) {
    try {
        const content = readFileSync(resolve(directory, filePath), "utf-8");
        const parsed = JSON.parse(content);
        return {
            body: typeof parsed.body === "string" ? parsed.body : "",
            inspectable: true,
        };
    }
    catch {
        return { body: "", inspectable: false };
    }
}
function readBodyFieldValue(directory, value) {
    if (!value.startsWith("@")) {
        return { body: value, inspectable: true };
    }
    try {
        return {
            body: readFileSync(resolve(directory, value.slice(1)), "utf-8"),
            inspectable: true,
        };
    }
    catch {
        return { body: "", inspectable: false };
    }
}
function isPullRequestCreateEndpoint(endpoint) {
    return /^\/?repos\/[^/\s]+\/[^/\s]+\/pulls\/?$/i.test(endpoint.trim());
}
function isPullRequestMergeEndpoint(endpoint) {
    return endpoint.trim().match(/^\/?repos\/[^/\s]+\/[^/\s]+\/pulls\/([^/\s]+)\/merge\/?$/i);
}
function parseGhApiInvocation(tokens) {
    let endpoint = "";
    let method = "";
    let hasFieldData = false;
    for (let index = 2; index < tokens.length; index += 1) {
        const token = tokens[index];
        if (!token) {
            continue;
        }
        if (FIELD_FLAGS.has(token)) {
            hasFieldData = true;
            index += 1;
            continue;
        }
        if (token.startsWith("--field=") || token.startsWith("--raw-field=")) {
            hasFieldData = true;
            continue;
        }
        if ((token.startsWith("-f") || token.startsWith("-F")) && token.length > 2) {
            hasFieldData = true;
            continue;
        }
        const explicitMethod = inlineOptionValue(token, "--method") || inlineOptionValue(token, "-X") || (token === "--method" || token === "-X" ? tokens[index + 1] ?? "" : "");
        if (explicitMethod) {
            method = explicitMethod.trim().toUpperCase();
            if (token === "--method" || token === "-X") {
                index += 1;
            }
            continue;
        }
        if (VALUE_FLAGS.has(token)) {
            index += 1;
            continue;
        }
        if (token.startsWith("-")) {
            continue;
        }
        if (!endpoint) {
            endpoint = token;
        }
    }
    return {
        endpoint,
        method: method || (hasFieldData ? "POST" : "GET"),
        tokens,
    };
}
function ghPrCreateInspection(tokens, directory) {
    for (let index = 3; index < tokens.length; index += 1) {
        const token = tokens[index];
        if (token === "--body" && index + 1 < tokens.length) {
            return { body: tokens[index + 1], inspectable: true };
        }
        if (token.startsWith("--body=")) {
            return { body: token.slice("--body=".length), inspectable: true };
        }
        if (token === "--body-file" && index + 1 < tokens.length) {
            return readBodyFieldValue(directory, `@${tokens[index + 1]}`);
        }
        if (token.startsWith("--body-file=")) {
            return readBodyFieldValue(directory, `@${token.slice("--body-file=".length)}`);
        }
    }
    return { body: "", inspectable: false };
}
function ghApiPrCreateInspection(tokens, directory) {
    for (let index = 2; index < tokens.length; index += 1) {
        const token = tokens[index];
        if (FIELD_FLAGS.has(token) && index + 1 < tokens.length) {
            const assignment = parseFieldAssignment(tokens[index + 1]);
            if (assignment?.key === "body") {
                return readBodyFieldValue(directory, assignment.value);
            }
            index += 1;
            continue;
        }
        if (token.startsWith("--field=") || token.startsWith("--raw-field=")) {
            const assignment = parseFieldAssignment(token.slice(token.indexOf("=") + 1));
            if (assignment?.key === "body") {
                return readBodyFieldValue(directory, assignment.value);
            }
            continue;
        }
        if ((token.startsWith("-f") || token.startsWith("-F")) && token.length > 2) {
            const assignment = parseFieldAssignment(token.slice(2));
            if (assignment?.key === "body") {
                return readBodyFieldValue(directory, assignment.value);
            }
            continue;
        }
        if (token === "--input" && index + 1 < tokens.length) {
            return readBodyFromInputFile(directory, tokens[index + 1]);
        }
        if (token.startsWith("--input=")) {
            return readBodyFromInputFile(directory, token.slice("--input=".length));
        }
    }
    return { body: "", inspectable: false };
}
function ghPrMergeHasStrategy(tokens) {
    return tokens.some((token, index) => index >= 3 && (token === "--merge" || token === "--squash" || token === "--rebase"));
}
function ghApiMergeHasStrategy(tokens) {
    for (let index = 2; index < tokens.length; index += 1) {
        const token = tokens[index];
        if (FIELD_FLAGS.has(token) && index + 1 < tokens.length) {
            const assignment = parseFieldAssignment(tokens[index + 1]);
            if (assignment?.key === "merge_method" && /^(merge|squash|rebase)$/i.test(assignment.value.trim())) {
                return true;
            }
            index += 1;
            continue;
        }
        if (token.startsWith("--field=") || token.startsWith("--raw-field=")) {
            const assignment = parseFieldAssignment(token.slice(token.indexOf("=") + 1));
            if (assignment?.key === "merge_method" && /^(merge|squash|rebase)$/i.test(assignment.value.trim())) {
                return true;
            }
            continue;
        }
        if ((token.startsWith("-f") || token.startsWith("-F")) && token.length > 2) {
            const assignment = parseFieldAssignment(token.slice(2));
            if (assignment?.key === "merge_method" && /^(merge|squash|rebase)$/i.test(assignment.value.trim())) {
                return true;
            }
        }
    }
    return false;
}
export function isGitHubPrCreateCommand(command) {
    const tokens = tokenizeShellCommand(command);
    for (let index = 0; index < tokens.length; index += 1) {
        if (!isGhBinary(tokens[index])) {
            continue;
        }
        const commandSlice = commandTokens(tokens, index);
        if (commandSlice[1] === "pr" && commandSlice[2] === "create") {
            return true;
        }
        if (commandSlice[1] !== "api") {
            continue;
        }
        const invocation = parseGhApiInvocation(commandSlice);
        if (invocation.method === "POST" && isPullRequestCreateEndpoint(invocation.endpoint)) {
            return true;
        }
    }
    return false;
}
export function inspectGitHubPrCreateBody(command, directory) {
    const tokens = tokenizeShellCommand(command);
    for (let index = 0; index < tokens.length; index += 1) {
        if (!isGhBinary(tokens[index])) {
            continue;
        }
        const commandSlice = commandTokens(tokens, index);
        if (commandSlice[1] === "pr" && commandSlice[2] === "create") {
            return ghPrCreateInspection(commandSlice, directory);
        }
        if (commandSlice[1] !== "api") {
            continue;
        }
        const invocation = parseGhApiInvocation(commandSlice);
        if (invocation.method === "POST" && isPullRequestCreateEndpoint(invocation.endpoint)) {
            return ghApiPrCreateInspection(commandSlice, directory);
        }
    }
    return { body: "", inspectable: false };
}
export function isGitHubPrMergeCommand(command) {
    const tokens = tokenizeShellCommand(command);
    for (let index = 0; index < tokens.length; index += 1) {
        if (!isGhBinary(tokens[index])) {
            continue;
        }
        const commandSlice = commandTokens(tokens, index);
        if (commandSlice[1] === "pr" && commandSlice[2] === "merge") {
            return true;
        }
        if (commandSlice[1] !== "api") {
            continue;
        }
        const invocation = parseGhApiInvocation(commandSlice);
        if (invocation.method === "PUT" && isPullRequestMergeEndpoint(invocation.endpoint)) {
            return true;
        }
    }
    return false;
}
export function extractGitHubPrMergeSelector(command) {
    const tokens = tokenizeShellCommand(command);
    for (let index = 0; index < tokens.length; index += 1) {
        if (!isGhBinary(tokens[index])) {
            continue;
        }
        const commandSlice = commandTokens(tokens, index);
        if (commandSlice[1] === "pr" && commandSlice[2] === "merge") {
            for (let argIndex = 3; argIndex < commandSlice.length; argIndex += 1) {
                const token = commandSlice[argIndex];
                if (!token || COMMAND_SEPARATOR_TOKENS.has(token)) {
                    break;
                }
                if (token.startsWith("-")) {
                    continue;
                }
                return token;
            }
            return "";
        }
        if (commandSlice[1] !== "api") {
            continue;
        }
        const invocation = parseGhApiInvocation(commandSlice);
        if (invocation.method !== "PUT") {
            continue;
        }
        const match = isPullRequestMergeEndpoint(invocation.endpoint);
        if (match) {
            return match[1] ?? "";
        }
    }
    return "";
}
export function gitHubPrMergeHasStrategy(command) {
    const tokens = tokenizeShellCommand(command);
    for (let index = 0; index < tokens.length; index += 1) {
        if (!isGhBinary(tokens[index])) {
            continue;
        }
        const commandSlice = commandTokens(tokens, index);
        if (commandSlice[1] === "pr" && commandSlice[2] === "merge") {
            return ghPrMergeHasStrategy(commandSlice);
        }
        if (commandSlice[1] !== "api") {
            continue;
        }
        const invocation = parseGhApiInvocation(commandSlice);
        if (invocation.method === "PUT" && isPullRequestMergeEndpoint(invocation.endpoint)) {
            return ghApiMergeHasStrategy(invocation.tokens);
        }
    }
    return false;
}
