import { execFileSync } from "node:child_process"
import { existsSync } from "node:fs"
import { dirname, isAbsolute, resolve } from "node:path"

interface ToolArgs {
  workdir?: string
  cwd?: string
  filePath?: string
  path?: string
  file_path?: string
}

interface ToolPayload {
  output?: { args?: ToolArgs }
  directory?: string
}

function targetFileArg(args: ToolArgs | undefined): string {
  const rawPath = String(args?.filePath ?? args?.path ?? args?.file_path ?? "").trim()
  if (!rawPath) {
    return ""
  }
  return rawPath
}

function nearestExistingParent(path: string): string {
  let current = path
  while (current && !existsSync(current)) {
    const parent = dirname(current)
    if (parent === current) {
      break
    }
    current = parent
  }
  return current
}

function gitTopLevel(directory: string): string {
  try {
    return execFileSync("git", ["rev-parse", "--show-toplevel"], {
      cwd: directory,
      encoding: "utf-8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim()
  } catch {
    return ""
  }
}

export function effectiveToolDirectory(payload: ToolPayload, fallbackDirectory: string): string {
  const payloadDirectory = typeof payload.directory === "string" && payload.directory.trim() ? payload.directory : ""
  const baseDirectory = payloadDirectory || fallbackDirectory
  const args = payload.output?.args
  const explicitWorkdir = String(args?.workdir ?? args?.cwd ?? "").trim()
  if (explicitWorkdir) {
    return isAbsolute(explicitWorkdir) ? explicitWorkdir : resolve(baseDirectory, explicitWorkdir)
  }
  const targetFile = targetFileArg(args)
  if (targetFile) {
    const absoluteTarget = isAbsolute(targetFile) ? targetFile : resolve(baseDirectory, targetFile)
    const existingParent = nearestExistingParent(dirname(absoluteTarget))
    return gitTopLevel(existingParent) || existingParent || baseDirectory
  }
  return baseDirectory
}
