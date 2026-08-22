import { execFileSync } from "node:child_process"
import { readFileSync, realpathSync } from "node:fs"
import { resolve } from "node:path"

export interface PrBodyInspection {
  body: string
  inspectable: boolean
}

const COMMAND_SEPARATOR_TOKENS = new Set(["&&", "||", ";", "|"])
const FIELD_FLAGS = new Set(["-f", "-F", "--field", "--raw-field"])
const VALUE_FLAGS = new Set(["-X", "--method", "--input", "-H", "--header", "--hostname"])
const PR_CREATE_VALUE_FLAGS = new Set([
  "--assignee",
  "--base",
  "--body",
  "--body-file",
  "--head",
  "--label",
  "--milestone",
  "--project",
  "--recover",
  "--reviewer",
  "--template",
  "--title",
  "-a",
  "-B",
  "-b",
  "-H",
  "-l",
  "-m",
  "-p",
  "-r",
  "-t",
])
const PR_CREATE_BOOLEAN_FLAGS = new Set([
  "--draft",
  "--dry-run",
  "--editor",
  "--fill",
  "--fill-first",
  "--fill-verbose",
  "--maintainer-can-modify",
  "--no-maintainer-edit",
  "--web",
])

export function tokenizeShellCommand(command: string): string[] {
  const matches = command.match(/&&|\|\||[;|]|(?:[^\s'";|&]+|'[^']*'|"[^"]*")+/g)
  if (!matches) {
    return []
  }
  return matches.map((token) =>
    token.replace(/'([^']*)'|"([^"]*)"/g, (_match, single, double) => single ?? double ?? "").replace(/\\(.)/g, "$1"),
  )
}

function isGhBinary(token: string): boolean {
  return /(?:^|[\\/])gh(?:\.exe)?$/i.test(token.replace(/^[(!]+/, ""))
}

function isEnvAssignment(token: string): boolean {
  return /^[A-Za-z_][A-Za-z0-9_]*=/.test(token)
}

function commandTokens(tokens: string[], startIndex: number): string[] {
  const command: string[] = []
  for (let index = startIndex; index < tokens.length; index += 1) {
    const token = tokens[index]
    if (COMMAND_SEPARATOR_TOKENS.has(token)) {
      break
    }
    command.push(token)
  }
  return command
}

function transparentGhCommandStart(tokens: string[]): number {
  let index = 0
  while (tokens[index] === "!") {
    index += 1
  }
  while (index < tokens.length && isEnvAssignment(tokens[index])) {
    index += 1
  }
  if (tokens[index] === "env") {
    index += 1
    while (index < tokens.length) {
      const token = tokens[index]
      if (token === "--") {
        index += 1
        break
      }
      if (isEnvAssignment(token) || token === "-i" || token === "-0" || token === "--ignore-environment" || token === "--null") {
        index += 1
        continue
      }
      if (token === "-u" || token === "--unset") {
        if (index + 1 >= tokens.length) {
          return -1
        }
        index += 2
        continue
      }
      if (token.startsWith("-u") || token.startsWith("--unset=")) {
        index += 1
        continue
      }
      if (token.startsWith("-")) {
        return -1
      }
      break
    }
  }
  if (tokens[index] === "command") {
    index += 1
    if (tokens[index] === "--") {
      index += 1
    } else if (tokens[index]?.startsWith("-")) {
      return -1
    }
  }
  if (tokens[index] === "exec") {
    index += 1
  }
  if (tokens[index] === "nice") {
    index += 1
    if (tokens[index] === "-n" && index + 1 < tokens.length) {
      index += 2
    } else if (tokens[index]?.startsWith("-")) {
      index += 1
    }
  }
  if (tokens[index] === "sudo") {
    index += 1
    while (tokens[index]?.startsWith("-")) {
      if (["-u", "-g", "-h", "-r", "-t", "-C"].includes(tokens[index]) && index + 1 < tokens.length) {
        index += 2
      } else {
        index += 1
      }
    }
  }
  return isGhBinary(tokens[index] ?? "") ? index : -1
}

function ghCommandSlices(command: string): string[][] {
  const tokens = tokenizeShellCommand(command)
  const commands: string[][] = []
  let index = 0
  while (index < tokens.length) {
    while (index < tokens.length && COMMAND_SEPARATOR_TOKENS.has(tokens[index])) {
      index += 1
    }
    if (index >= tokens.length) {
      break
    }
    let commandStart = index
    while (commandStart < tokens.length && isEnvAssignment(tokens[commandStart])) {
      commandStart += 1
    }
    if (commandStart >= tokens.length || COMMAND_SEPARATOR_TOKENS.has(tokens[commandStart])) {
      index = commandStart + 1
      continue
    }
    const rawSlice = commandTokens(tokens, commandStart)
    const ghStart = transparentGhCommandStart(rawSlice)
    if (ghStart >= 0) {
      commands.push(rawSlice.slice(ghStart))
    }
    index = commandStart + rawSlice.length + 1
  }
  return commands
}

function shellWrappedGhCommandSlices(command: string): string[][] {
  const tokens = tokenizeShellCommand(command)
  const shellIndex = tokens.findIndex((token) => /(?:^|[\\/])(?:bash|sh|zsh)(?:\.exe)?$/i.test(token))
  if (shellIndex < 0 || tokens[shellIndex + 1] !== "-c" || !tokens[shellIndex + 2]) {
    return []
  }
  return ghCommandSlices(tokens[shellIndex + 2])
}

function hasShellControlSyntax(command: string): boolean {
  let quote: "'" | '"' | null = null
  for (let index = 0; index < command.length; index += 1) {
    const char = command[index]
    const next = command[index + 1] ?? ""
    if (quote) {
      if (char === quote) {
        quote = null
      } else if (char === "\\" && quote === '"') {
        index += 1
      } else if (char === "`" || (char === "$" && next === "(")) {
        return true
      }
      continue
    }
    if (char === "'" || char === '"') {
      quote = char
      continue
    }
    if (char === "\\") {
      index += 1
      continue
    }
    if ([";", "&", "|", "<", ">", "`", "\n", "\r"].includes(char)) {
      return true
    }
    if (char === "$" && next === "(") {
      return true
    }
  }
  return quote !== null
}

function ghPrCreateIndex(tokens: string[]): number {
  if (tokens[1] === "api") {
    return -1
  }
  for (let index = 1; index + 1 < tokens.length; index += 1) {
    if (tokens[index] === "pr" && tokens[index + 1] === "create") {
      return index
    }
  }
  return -1
}

function hasGitHubRepositoryOverride(command: string, tokens: string[]): boolean {
  const rawTokens = tokenizeShellCommand(command)
  const executableIndex = rawTokens.findIndex((token) => isGhBinary(token))
  const overrideUnsets = new Set<string>()
  for (let index = 0; index >= 0 && index < executableIndex; index += 1) {
    const token = rawTokens[index]
    let key = ""
    if ((token === "-u" || token === "--unset") && index + 1 < executableIndex) {
      key = rawTokens[index + 1]
      index += 1
    } else if (token.startsWith("-u") && token.length > 2) {
      key = token.slice(2)
    } else if (token.startsWith("--unset=")) {
      key = token.slice("--unset=".length)
    }
    if (key === "GH_REPO" || key === "GH_HOST") {
      overrideUnsets.add(key)
    }
  }
  if (
    executableIndex >= 0 &&
    rawTokens
      .slice(0, executableIndex)
      .some((token) => /^GH_(?:REPO|HOST)=/.test(token))
  ) {
    return true
  }
  if ((process.env.GH_REPO && !overrideUnsets.has("GH_REPO")) || (process.env.GH_HOST && !overrideUnsets.has("GH_HOST"))) {
    return true
  }
  return tokens.some(
    (token) =>
      token === "--repo" ||
      token === "-R" ||
      token === "--hostname" ||
      token.startsWith("--repo=") ||
      token.startsWith("-R") ||
      token.startsWith("--hostname="),
  )
}

function mayInvokeGitHubPrCreateThroughWrapper(command: string): boolean {
  const directCommands = ghCommandSlices(command)
  const wrappedCommands = shellWrappedGhCommandSlices(command)
  const isPrCreate = (tokens: string[]): boolean => {
    if (ghPrCreateIndex(tokens) >= 0 || isGraphQlPullRequestCreate(tokens)) {
      return true
    }
    const invocation = parseGhApiInvocation(tokens)
    return invocation.method === "POST" && isPullRequestCreateEndpoint(invocation.endpoint)
  }
  if (!directCommands.some(isPrCreate) && !wrappedCommands.some(isPrCreate)) {
    return false
  }
  return wrappedCommands.some(isPrCreate) || hasShellControlSyntax(command)
}

function prCreateHead(
  tokens: string[],
  startIndex: number,
): { specified: boolean; value: string } | null {
  let head: string | null = null
  for (let index = startIndex + 2; index < tokens.length; index += 1) {
    const token = tokens[index]
    if (token === "--") {
      break
    }
    let value = ""
    let headFlag = false
    if (token === "--head" || token === "-H") {
      headFlag = true
      value = tokens[index + 1] ?? ""
      index += 1
    } else if (token.startsWith("--head=")) {
      headFlag = true
      value = token.slice("--head=".length)
    } else if (token.startsWith("-H") && token.length > 2) {
      headFlag = true
      value = token.slice(token.startsWith("-H=") ? 3 : 2)
    }
    if (headFlag) {
      if (head !== null || !value) {
        return null
      }
      head = value
      continue
    }
    if (PR_CREATE_VALUE_FLAGS.has(token)) {
      if (index + 1 >= tokens.length || tokens[index + 1] === "--") {
        return null
      }
      index += 1
      continue
    }
    if ([...PR_CREATE_VALUE_FLAGS].some((flag) => token.startsWith(`${flag}=`))) {
      continue
    }
    if (["-a", "-B", "-b", "-l", "-m", "-p", "-r", "-t"].some((flag) => token.startsWith(flag) && token.length > flag.length)) {
      continue
    }
    if (PR_CREATE_BOOLEAN_FLAGS.has(token)) {
      continue
    }
    if (token.startsWith("-")) {
      return null
    }
    return null
  }
  return head === null ? { specified: false, value: "" } : { specified: true, value: head }
}

function isLocalBranchName(branch: string): boolean {
  if (!branch || branch.includes(":") || !/^[A-Za-z0-9][A-Za-z0-9._/-]*$/.test(branch)) {
    return false
  }
  try {
    execFileSync("git", ["check-ref-format", "--branch", branch], { stdio: "ignore" })
    return true
  } catch {
    return false
  }
}

// Resolves explicit gh pr create heads only. API-based PR creation remains
// fail-closed when branch-bound validation evidence is required.
export function resolveGitHubPrCreateEvidenceDirectory(command: string, directory: string): string | null {
  if (hasShellControlSyntax(command)) {
    return null
  }
  const prCommands = ghCommandSlices(command)
    .map((tokens) => ({ tokens, index: ghPrCreateIndex(tokens) }))
    .filter((commandSlice) => commandSlice.index >= 0)
  if (prCommands.length !== 1) {
    return null
  }
  if (hasGitHubRepositoryOverride(command, prCommands[0].tokens)) {
    return null
  }
  const head = prCreateHead(prCommands[0].tokens, prCommands[0].index)
  if (!head) {
    return null
  }
  if (!head.specified) {
    return directory
  }
  if (!isLocalBranchName(head.value)) {
    return null
  }
  try {
    const worktrees = execFileSync("git", ["-C", directory, "worktree", "list", "--porcelain"], {
      encoding: "utf-8",
      stdio: ["ignore", "pipe", "ignore"],
    })
    const expectedBranch = `refs/heads/${head.value}`
    const matches: string[] = []
    for (const entry of worktrees.split("\n\n")) {
      const lines = entry.split("\n")
      const worktree = lines.find((line) => line.startsWith("worktree "))?.slice("worktree ".length)
      const branch = lines.find((line) => line.startsWith("branch "))?.slice("branch ".length)
      if (worktree && branch === expectedBranch) {
        matches.push(realpathSync(worktree))
      }
    }
    return matches.length === 1 ? matches[0] : null
  } catch {
    // Evidence lookup must fail closed when Git cannot prove the worktree.
  }
  return null
}

function inlineOptionValue(token: string, name: string): string {
  if (token.startsWith(`${name}=`)) {
    return token.slice(name.length + 1)
  }
  if (name.length === 2 && token.startsWith(name) && token.length > name.length) {
    return token.slice(name.length)
  }
  return ""
}

function parseFieldAssignment(token: string): { key: string; value: string } | null {
  const equalsIndex = token.indexOf("=")
  if (equalsIndex <= 0) {
    return null
  }
  return {
    key: token.slice(0, equalsIndex).trim().toLowerCase(),
    value: token.slice(equalsIndex + 1),
  }
}

function readBodyFromInputFile(directory: string, filePath: string): PrBodyInspection {
  try {
    const content = readFileSync(resolve(directory, filePath), "utf-8")
    const parsed = JSON.parse(content) as { body?: unknown }
    return {
      body: typeof parsed.body === "string" ? parsed.body : "",
      inspectable: true,
    }
  } catch {
    return { body: "", inspectable: false }
  }
}

function readBodyFieldValue(directory: string, value: string): PrBodyInspection {
  if (!value.startsWith("@")) {
    return { body: value, inspectable: true }
  }
  try {
    return {
      body: readFileSync(resolve(directory, value.slice(1)), "utf-8"),
      inspectable: true,
    }
  } catch {
    return { body: "", inspectable: false }
  }
}

function isPullRequestCreateEndpoint(endpoint: string): boolean {
  return /^\/?repos\/[^/\s]+\/[^/\s]+\/pulls\/?$/i.test(endpoint.trim())
}

function graphQlPayloadHasCreatePullRequest(value: string): boolean {
  let source = ""
  let quote = false
  let comment = false
  for (let index = 0; index < value.length; index += 1) {
    const char = value[index]
    if (comment) {
      if (char === "\n" || char === "\r") {
        comment = false
        source += char
      }
      continue
    }
    if (quote) {
      if (char === "\\") {
        index += 1
      } else if (char === '"') {
        quote = false
      }
      source += " "
      continue
    }
    if (char === "#") {
      comment = true
      continue
    }
    if (char === '"') {
      quote = true
      source += " "
      continue
    }
    source += char
  }
  return /(?:^|[^A-Za-z0-9_])(?:[A-Za-z_][A-Za-z0-9_]*\s*:\s*)?createPullRequest\s*\(/.test(source)
}

function isGraphQlPullRequestCreate(tokens: string[]): boolean {
  if (tokens[1] !== "api" || !tokens.some((token) => /^\/?graphql$/i.test(token))) {
    return false
  }
  for (let index = 2; index < tokens.length; index += 1) {
    const token = tokens[index]
    if (token === "--input" || token.startsWith("--input=")) {
      return true
    }
    let assignment: { key: string; value: string } | null = null
    if (FIELD_FLAGS.has(token) && index + 1 < tokens.length) {
      assignment = parseFieldAssignment(tokens[++index])
    } else if (token.startsWith("--field=") || token.startsWith("--raw-field=")) {
      assignment = parseFieldAssignment(token.slice(token.indexOf("=") + 1))
    } else if ((token.startsWith("-f") || token.startsWith("-F")) && token.length > 2) {
      assignment = parseFieldAssignment(token.slice(2))
    }
    if (assignment?.key === "query") {
      if (assignment.value.startsWith("@") || graphQlPayloadHasCreatePullRequest(assignment.value)) {
        return true
      }
    }
  }
  return false
}
function isPullRequestMergeEndpoint(endpoint: string): RegExpMatchArray | null {
  return endpoint.trim().match(/^\/?repos\/[^/\s]+\/[^/\s]+\/pulls\/([^/\s]+)\/merge\/?$/i)
}

interface GhApiInvocation {
  endpoint: string
  method: string
  tokens: string[]
}

function parseGhApiInvocation(tokens: string[]): GhApiInvocation {
  let endpoint = ""
  let method = ""
  let hasFieldData = false
  for (let index = 2; index < tokens.length; index += 1) {
    const token = tokens[index]
    if (!token) {
      continue
    }
    if (FIELD_FLAGS.has(token)) {
      hasFieldData = true
      index += 1
      continue
    }
    if (token.startsWith("--field=") || token.startsWith("--raw-field=")) {
      hasFieldData = true
      continue
    }
    if ((token.startsWith("-f") || token.startsWith("-F")) && token.length > 2) {
      hasFieldData = true
      continue
    }
    if (token === "--input" || token.startsWith("--input=")) {
      hasFieldData = true
      if (token === "--input") {
        index += 1
      }
      continue
    }
    const explicitMethod =
      inlineOptionValue(token, "--method") || inlineOptionValue(token, "-X") || (token === "--method" || token === "-X" ? tokens[index + 1] ?? "" : "")
    if (explicitMethod) {
      method = explicitMethod.trim().toUpperCase()
      if (token === "--method" || token === "-X") {
        index += 1
      }
      continue
    }
    if (VALUE_FLAGS.has(token)) {
      index += 1
      continue
    }
    if (token.startsWith("-")) {
      continue
    }
    if (!endpoint) {
      endpoint = token
    }
  }
  return {
    endpoint,
    method: method || (hasFieldData ? "POST" : "GET"),
    tokens,
  }
}

function ghPrMergeHasStrategy(tokens: string[]): boolean {
  return tokens.some((token, index) => index >= 3 && (token === "--merge" || token === "--squash" || token === "--rebase"))
}

function ghApiMergeHasStrategy(tokens: string[]): boolean {
  for (let index = 2; index < tokens.length; index += 1) {
    const token = tokens[index]
    if (FIELD_FLAGS.has(token) && index + 1 < tokens.length) {
      const assignment = parseFieldAssignment(tokens[index + 1])
      if (assignment?.key === "merge_method" && /^(merge|squash|rebase)$/i.test(assignment.value.trim())) {
        return true
      }
      index += 1
      continue
    }
    if (token.startsWith("--field=") || token.startsWith("--raw-field=")) {
      const assignment = parseFieldAssignment(token.slice(token.indexOf("=") + 1))
      if (assignment?.key === "merge_method" && /^(merge|squash|rebase)$/i.test(assignment.value.trim())) {
        return true
      }
      continue
    }
    if ((token.startsWith("-f") || token.startsWith("-F")) && token.length > 2) {
      const assignment = parseFieldAssignment(token.slice(2))
      if (assignment?.key === "merge_method" && /^(merge|squash|rebase)$/i.test(assignment.value.trim())) {
        return true
      }
    }
  }
  return false
}

export function isGitHubPrMergeCommand(command: string): boolean {
  for (const commandSlice of ghCommandSlices(command)) {
    if (commandSlice[1] === "pr" && commandSlice[2] === "merge") {
      return true
    }
    if (commandSlice[1] !== "api") {
      continue
    }
    const invocation = parseGhApiInvocation(commandSlice)
    if (invocation.method === "PUT" && isPullRequestMergeEndpoint(invocation.endpoint)) {
      return true
    }
  }
  return false
}

export function extractGitHubPrMergeSelector(command: string): string {
  for (const commandSlice of ghCommandSlices(command)) {
    if (commandSlice[1] === "pr" && commandSlice[2] === "merge") {
      for (let argIndex = 3; argIndex < commandSlice.length; argIndex += 1) {
        const token = commandSlice[argIndex]
        if (!token || COMMAND_SEPARATOR_TOKENS.has(token)) {
          break
        }
        if (token.startsWith("-")) {
          continue
        }
        return token
      }
      return ""
    }
    if (commandSlice[1] !== "api") {
      continue
    }
    const invocation = parseGhApiInvocation(commandSlice)
    if (invocation.method !== "PUT") {
      continue
    }
    const match = isPullRequestMergeEndpoint(invocation.endpoint)
    if (match) {
      return match[1] ?? ""
    }
  }
  return ""
}

export function gitHubPrMergeHasStrategy(command: string): boolean {
  for (const commandSlice of ghCommandSlices(command)) {
    if (commandSlice[1] == "pr" && commandSlice[2] == "merge") {
      return ghPrMergeHasStrategy(commandSlice)
    }
    if (commandSlice[1] !== "api") {
      continue
    }
    const invocation = parseGhApiInvocation(commandSlice)
    if (invocation.method === "PUT" && isPullRequestMergeEndpoint(invocation.endpoint)) {
      return ghApiMergeHasStrategy(invocation.tokens)
    }
  }
  return false
}

function ghPrCreateInspection(tokens: string[], directory: string): PrBodyInspection {
  const startIndex = ghPrCreateIndex(tokens)
  let body: PrBodyInspection | null = null
  const recordBody = (next: PrBodyInspection): boolean => {
    if (body) {
      return false
    }
    body = next
    return true
  }
  for (let index = startIndex + 2; index < tokens.length; index += 1) {
    const token = tokens[index]
    if (token === "--") {
      break
    }
    if (token === "--body" || token === "-b") {
      if (index + 1 >= tokens.length || !recordBody({ body: tokens[index + 1], inspectable: true })) {
        return { body: "", inspectable: false }
      }
      index += 1
      continue
    }
    if (token.startsWith("--body=")) {
      if (!recordBody({ body: token.slice("--body=".length), inspectable: true })) {
        return { body: "", inspectable: false }
      }
      continue
    }
    if (token.startsWith("-b") && token.length > 2) {
      if (!recordBody({ body: token.slice(2), inspectable: true })) {
        return { body: "", inspectable: false }
      }
      continue
    }
    if (token === "--body-file") {
      if (index + 1 >= tokens.length || !recordBody(readBodyFieldValue(directory, `@${tokens[index + 1]}`))) {
        return { body: "", inspectable: false }
      }
      index += 1
      continue
    }
    if (token.startsWith("--body-file=")) {
      if (!recordBody(readBodyFieldValue(directory, `@${token.slice("--body-file=".length)}`))) {
        return { body: "", inspectable: false }
      }
      continue
    }
    if (PR_CREATE_VALUE_FLAGS.has(token)) {
      if (index + 1 >= tokens.length) {
        return { body: "", inspectable: false }
      }
      index += 1
      continue
    }
    if ([...PR_CREATE_VALUE_FLAGS].some((flag) => token.startsWith(`${flag}=`))) {
      continue
    }
    if (["-a", "-B", "-l", "-m", "-p", "-r", "-t"].some((flag) => token.startsWith(flag) && token.length > flag.length)) {
      continue
    }
    if (PR_CREATE_BOOLEAN_FLAGS.has(token)) {
      continue
    }
    if (token.startsWith("-")) {
      return { body: "", inspectable: false }
    }
  }
  return body ?? { body: "", inspectable: false }
}

function ghApiPrCreateInspection(tokens: string[], directory: string): PrBodyInspection {
  let body: PrBodyInspection | null = null
  const recordBody = (next: PrBodyInspection): boolean => {
    if (body) {
      return false
    }
    body = next
    return true
  }
  for (let index = 2; index < tokens.length; index += 1) {
    const token = tokens[index]
    if (FIELD_FLAGS.has(token) && index + 1 < tokens.length) {
      const assignment = parseFieldAssignment(tokens[index + 1])
      if (assignment?.key === "body" && !recordBody(readBodyFieldValue(directory, assignment.value))) {
        return { body: "", inspectable: false }
      }
      index += 1
      continue
    }
    if (token.startsWith("--field=") || token.startsWith("--raw-field=")) {
      const assignment = parseFieldAssignment(token.slice(token.indexOf("=") + 1))
      if (assignment?.key === "body" && !recordBody(readBodyFieldValue(directory, assignment.value))) {
        return { body: "", inspectable: false }
      }
      continue
    }
    if ((token.startsWith("-f") || token.startsWith("-F")) && token.length > 2) {
      const assignment = parseFieldAssignment(token.slice(2))
      if (assignment?.key === "body" && !recordBody(readBodyFieldValue(directory, assignment.value))) {
        return { body: "", inspectable: false }
      }
      continue
    }
    if (token === "--input" && index + 1 < tokens.length) {
      if (!recordBody(readBodyFromInputFile(directory, tokens[index + 1]))) {
        return { body: "", inspectable: false }
      }
      index += 1
      continue
    }
    if (token.startsWith("--input=")) {
      if (!recordBody(readBodyFromInputFile(directory, token.slice("--input=".length)))) {
        return { body: "", inspectable: false }
      }
    }
  }
  return body ?? { body: "", inspectable: false }
}

export function isGitHubPrCreateCommand(command: string): boolean {
  if (mayInvokeGitHubPrCreateThroughWrapper(command)) {
    return true
  }
  if (ghCommandSlices(command).some(isGraphQlPullRequestCreate)) {
    return true
  }
  for (const commandSlice of ghCommandSlices(command)) {
    if (ghPrCreateIndex(commandSlice) >= 0) {
      return true
    }
    if (commandSlice[1] !== "api") {
      continue
    }
    const invocation = parseGhApiInvocation(commandSlice)
    if (invocation.method === "POST" && isPullRequestCreateEndpoint(invocation.endpoint)) {
      return true
    }
  }
  return false
}

export function inspectGitHubPrCreateBody(command: string, directory: string): PrBodyInspection {
  for (const commandSlice of ghCommandSlices(command)) {
    if (ghPrCreateIndex(commandSlice) >= 0) {
      return ghPrCreateInspection(commandSlice, directory)
    }
    if (commandSlice[1] !== "api") {
      continue
    }
    const invocation = parseGhApiInvocation(commandSlice)
    if (invocation.method === "POST" && isPullRequestCreateEndpoint(invocation.endpoint)) {
      return ghApiPrCreateInspection(commandSlice, directory)
    }
  }
  return { body: "", inspectable: false }
}
