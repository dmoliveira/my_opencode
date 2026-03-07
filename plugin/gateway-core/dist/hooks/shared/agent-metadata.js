import { readFileSync } from "node:fs";
import { join } from "node:path";
let cacheKey = "";
let cacheValue = new Map();
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
        cost_tier: typeof source.cost_tier === "string" && source.cost_tier.trim()
            ? source.cost_tier.trim()
            : undefined,
        default_category: typeof source.default_category === "string" && source.default_category.trim()
            ? source.default_category.trim()
            : undefined,
        fallback_policy: typeof source.fallback_policy === "string" && source.fallback_policy.trim()
            ? source.fallback_policy.trim()
            : undefined,
        triggers: cleanStringArray(source.triggers),
        avoid_when: cleanStringArray(source.avoid_when),
        denied_tools: cleanStringArray(source.denied_tools),
    };
}
function buildMap(directory) {
    const map = new Map();
    const names = [
        "orchestrator",
        "explore",
        "librarian",
        "oracle",
        "verifier",
        "reviewer",
        "release-scribe",
        "strategic-planner",
        "ambiguity-analyst",
        "plan-critic",
    ];
    for (const name of names) {
        const path = join(directory, "agent", "specs", `${name}.json`);
        try {
            const raw = JSON.parse(readFileSync(path, "utf-8"));
            map.set(name, normalizeMetadata(raw.metadata));
        }
        catch {
            map.set(name, {});
        }
    }
    return map;
}
export function loadAgentMetadata(directory) {
    if (cacheKey === directory && cacheValue.size > 0) {
        return cacheValue;
    }
    cacheKey = directory;
    cacheValue = buildMap(directory);
    return cacheValue;
}
