import { lstatSync, readdirSync, realpathSync, statSync } from "node:fs"
import { basename, dirname, isAbsolute, relative, resolve, sep } from "node:path"

export type TaskerReadAuthority = { worktree: string; paths: readonly string[] }
type LocalScope = { path: string; directory: boolean }
function inside(root: string, target: string): boolean {
  const path = relative(root, target)
  return path === "" || !path.startsWith(`..${sep}`) && path !== ".." && !isAbsolute(path)
}
function canonical(path: string): string {
  try { return realpathSync(path) } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT" || dirname(path) === path) throw error
    return resolve(canonical(dirname(path)), basename(path))
  }
}
function localScopes(root: string, paths: readonly string[]): LocalScope[] {
  return paths.filter((path) => !path.startsWith("https://")).map((path) => {
    if (/[?*\[\]{}]/.test(path)) throw new Error("read grants use literal paths")
    const actual = canonical(resolve(root, path))
    if (!inside(root, actual)) throw new Error("scope escaped worktree")
    let directory = false
    try { directory = statSync(actual).isDirectory() } catch { /* Missing explicit files may be inspected for absence. */ }
    return { path: actual, directory }
  })
}
function covered(scopes: LocalScope[], path: string, directory = false): boolean {
  return scopes.some((scope) => scope.directory ? inside(scope.path, path) : !directory && (scope.path === path))
}
/** Native search tools may follow links; reject escaping trees before invocation. */
function safeSearchTree(root: string, scopes: LocalScope[], start: string): boolean {
  const pending = [start], visited = new Set<string>()
  let budget = 4096
  while (pending.length) {
    if (--budget < 0) return false
    const path = pending.pop()!
    const actual = canonical(path)
    if (!inside(root, actual) || !covered(scopes, actual)) return false
    let info
    try { info = lstatSync(actual) } catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") continue; return false }
    if (!info.isDirectory() || visited.has(actual)) continue
    visited.add(actual)
    for (const name of readdirSync(actual)) pending.push(resolve(actual, name))
  }
  return true
}
/** Authorizes the actual native tool target, not just instructions in its prompt. */
export function authorizeTaskerRead(tool: string, args: Record<string, unknown>, authority: TaskerReadAuthority): boolean {
  try {
    if (tool === "webfetch") {
      if (typeof args.url !== "string") return false
      const url = new URL(args.url)
      if (url.protocol !== "https:" || url.username || url.password) return false
      url.hash = ""
      const allowed = authority.paths.some((value) => {
        if (!value.startsWith("https://")) return false
        const reference = new URL(value); reference.hash = ""
        return reference.href === url.href
      })
      if (allowed) args.url = url.href
      return allowed
    }
    // Search services cannot be constrained to an exact declared reference.
    if (!["read", "list", "glob", "grep"].includes(tool)) return false
    const root = realpathSync(authority.worktree)
    if (root !== resolve(authority.worktree)) return false
    const scopes = localScopes(root, authority.paths)
    const key = tool === "read" ? "filePath" : "path"
    const raw = args[key] ?? root
    if (typeof raw !== "string" || /[\0\r\n]/.test(raw)) return false
    const path = canonical(resolve(root, raw))
    if (!inside(root, path)) return false
    let directory = false
    try { directory = statSync(path).isDirectory() } catch { /* Native tool reports a missing permitted target. */ }
    if (!covered(scopes, path, directory || tool === "list")) return false
    if (tool === "glob") {
      if (typeof args.pattern !== "string" || !args.pattern || args.pattern.length > 2048 || /[\0\r\n:]/.test(args.pattern) || isAbsolute(args.pattern) || args.pattern.startsWith("\\") || args.pattern.split(/[\\/]/).includes("..")) return false
    }
    if (tool === "glob" || tool === "grep" || tool === "list") {
      if (!safeSearchTree(root, scopes, path)) return false
      if (typeof args.include === "string" && (isAbsolute(args.include) || args.include.split(/[\\/]/).includes(".."))) return false
    }
    args[key] = path
    return true
  } catch { return false }
}
