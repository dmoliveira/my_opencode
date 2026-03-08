import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, isAbsolute, resolve } from "node:path";
function targetFileArg(args) {
    const rawPath = String(args?.filePath ?? args?.path ?? args?.file_path ?? "").trim();
    if (!rawPath) {
        return "";
    }
    return rawPath;
}
function patchTargetPaths(args) {
    const patchText = String(args?.patchText ?? args?.patch_text ?? "");
    if (!patchText.trim()) {
        return [];
    }
    const paths = [];
    for (const line of patchText.split(/\r?\n/)) {
        const match = line.match(/^\*\*\*\s+(?:Add|Update|Delete)\s+File:\s+(.+)\s*$/);
        if (match?.[1]) {
            paths.push(match[1].trim());
            continue;
        }
        const moveMatch = line.match(/^\*\*\*\s+Move to:\s+(.+)\s*$/);
        if (moveMatch?.[1]) {
            paths.push(moveMatch[1].trim());
        }
    }
    return paths;
}
function nearestExistingParent(path) {
    let current = path;
    while (current && !existsSync(current)) {
        const parent = dirname(current);
        if (parent === current) {
            break;
        }
        current = parent;
    }
    return current;
}
function gitTopLevel(directory) {
    try {
        return execFileSync("git", ["rev-parse", "--show-toplevel"], {
            cwd: directory,
            encoding: "utf-8",
            stdio: ["ignore", "pipe", "ignore"],
        }).trim();
    }
    catch {
        return "";
    }
}
function resolveTargetDirectory(baseDirectory, targetPath) {
    const absoluteTarget = isAbsolute(targetPath) ? targetPath : resolve(baseDirectory, targetPath);
    const existingParent = nearestExistingParent(dirname(absoluteTarget));
    return gitTopLevel(existingParent) || existingParent || baseDirectory;
}
export function effectiveToolDirectory(payload, fallbackDirectory) {
    const payloadDirectory = typeof payload.directory === "string" && payload.directory.trim() ? payload.directory : "";
    const baseDirectory = payloadDirectory || fallbackDirectory;
    const args = payload.output?.args;
    const explicitWorkdir = String(args?.workdir ?? args?.cwd ?? "").trim();
    if (explicitWorkdir) {
        return isAbsolute(explicitWorkdir) ? explicitWorkdir : resolve(baseDirectory, explicitWorkdir);
    }
    const targetFile = targetFileArg(args);
    if (targetFile) {
        return resolveTargetDirectory(baseDirectory, targetFile);
    }
    const patchTargets = patchTargetPaths(args);
    if (patchTargets.length > 0) {
        const directories = [...new Set(patchTargets.map((target) => resolveTargetDirectory(baseDirectory, target)))];
        if (directories.length === 1) {
            return directories[0];
        }
    }
    return baseDirectory;
}
