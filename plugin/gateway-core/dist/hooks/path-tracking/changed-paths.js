// Returns normalized relative paths extracted from apply_patch text.
function parsePatchPaths(patchText) {
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
// Returns changed file paths hinted by incoming tool arguments.
export function changedPathsFromToolPayload(payload) {
    const eventPayload = (payload ?? {});
    const tool = String(eventPayload.input?.tool ?? "").toLowerCase();
    const args = eventPayload.output?.args;
    if (!args) {
        return [];
    }
    if (tool === "write" || tool === "edit") {
        const value = String(args.filePath ?? args.path ?? args.file_path ?? "").trim();
        return value ? [value] : [];
    }
    if (tool !== "apply_patch") {
        return [];
    }
    const patchText = String(args.patchText ?? args.patch_text ?? "");
    if (!patchText.trim()) {
        return [];
    }
    return parsePatchPaths(patchText);
}
