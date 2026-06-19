import { readdirSync, readFileSync } from "node:fs";
import { basename, join } from "node:path";
const cacheByDirectory = new Map();
function cleanStringArray(value) {
    if (!Array.isArray(value)) {
        return [];
    }
    return value
        .filter((item) => typeof item === "string")
        .map((item) => item.trim())
        .filter((item) => item.length > 0);
}
function normalizeMetadata(value) {
    if (!value || typeof value !== "object") {
        return {};
    }
    const source = value;
    return {
        model: typeof source.model === "string" && source.model.trim()
            ? source.model.trim()
            : undefined,
        mode: typeof source.mode === "string" && source.mode.trim()
            ? source.mode.trim()
            : undefined,
        cost_tier: typeof source.cost_tier === "string" && source.cost_tier.trim()
            ? source.cost_tier.trim()
            : undefined,
        default_category: typeof source.default_category === "string" &&
            source.default_category.trim()
            ? source.default_category.trim()
            : undefined,
        fallback_policy: typeof source.fallback_policy === "string" &&
            source.fallback_policy.trim()
            ? source.fallback_policy.trim()
            : undefined,
        triggers: cleanStringArray(source.triggers),
        avoid_when: cleanStringArray(source.avoid_when),
        denied_tools: cleanStringArray(source.denied_tools),
    };
}
function frontmatterModel(directory, name) {
    const path = join(directory, "agent", `${name}.md`);
    try {
        const text = readFileSync(path, "utf-8");
        if (!text.startsWith("---\n")) {
            return undefined;
        }
        const lines = text.split(/\r?\n/);
        for (let idx = 1; idx < lines.length; idx += 1) {
            const line = lines[idx]?.trim() ?? "";
            if (line === "---") {
                break;
            }
            const match = line.match(/^model:\s*(.+)$/);
            if (match?.[1]?.trim()) {
                return match[1].trim();
            }
        }
    }
    catch {
        return undefined;
    }
    return undefined;
}
function collectAllowedTools(value) {
    if (!value || typeof value !== "object") {
        return [];
    }
    const source = value;
    return Object.entries(source)
        .filter(([tool, enabled]) => typeof tool === "string" && enabled === true)
        .map(([tool]) => tool.trim())
        .filter((tool) => tool.length > 0);
}
function buildMap(directory) {
    const map = new Map();
    const specsDir = join(directory, "agent", "specs");
    let names = [];
    try {
        names = readdirSync(specsDir)
            .filter((entry) => entry.endsWith(".json"))
            .map((entry) => basename(entry, ".json").trim())
            .filter(Boolean)
            .sort((a, b) => a.localeCompare(b));
    }
    catch {
        names = [];
    }
    for (const name of names) {
        const path = join(specsDir, `${name}.json`);
        try {
            const raw = JSON.parse(readFileSync(path, "utf-8"));
            map.set(name, {
                ...normalizeMetadata(raw.metadata),
                mode: typeof raw.mode === "string" && raw.mode.trim()
                    ? raw.mode.trim()
                    : undefined,
                model: frontmatterModel(directory, name),
                allowed_tools: collectAllowedTools(raw.tools),
            });
        }
        catch {
            map.set(name, {});
        }
    }
    return map;
}
export function loadAgentMetadata(directory) {
    const cached = cacheByDirectory.get(directory);
    if (cached && cached.size > 0) {
        return cached;
    }
    const built = buildMap(directory);
    cacheByDirectory.set(directory, built);
    return built;
}
