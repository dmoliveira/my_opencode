import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
const activeByDelegation = new Map();
const timeline = [];
let statePath = "";
let stateMaxEntries = 300;
let persistenceEnabled = false;
let loaded = false;
function normalizeRecord(value) {
    if (!value || typeof value !== "object") {
        return null;
    }
    const source = value;
    const status = source.status === "failed" ? "failed" : source.status === "completed" ? "completed" : null;
    const sessionId = String(source.sessionId ?? "").trim();
    const subagentType = String(source.subagentType ?? "").trim();
    const category = String(source.category ?? "").trim();
    const reasonCode = String(source.reasonCode ?? "").trim();
    const startedAt = Number(source.startedAt ?? NaN);
    const endedAt = Number(source.endedAt ?? NaN);
    const durationMs = Number(source.durationMs ?? NaN);
    if (!status ||
        !sessionId ||
        !subagentType ||
        !category ||
        !reasonCode ||
        !Number.isFinite(startedAt) ||
        !Number.isFinite(endedAt) ||
        !Number.isFinite(durationMs)) {
        return null;
    }
    const childRunId = String(source.childRunId ?? "").trim() || undefined;
    const traceId = String(source.traceId ?? "").trim() || undefined;
    return {
        sessionId,
        childRunId,
        subagentType,
        category,
        status,
        reasonCode,
        startedAt,
        endedAt,
        durationMs,
        traceId,
    };
}
function trimTimeline(maxEntries) {
    if (maxEntries <= 0) {
        timeline.splice(0, timeline.length);
        return;
    }
    while (timeline.length > maxEntries) {
        timeline.shift();
    }
}
function persist() {
    if (!persistenceEnabled || !statePath) {
        return;
    }
    const payload = { timeline };
    mkdirSync(dirname(statePath), { recursive: true });
    writeFileSync(statePath, JSON.stringify(payload, null, 2), "utf-8");
}
function load() {
    if (loaded) {
        return;
    }
    loaded = true;
    if (!persistenceEnabled || !statePath || !existsSync(statePath)) {
        return;
    }
    try {
        const parsed = JSON.parse(readFileSync(statePath, "utf-8"));
        const records = Array.isArray(parsed?.timeline)
            ? parsed.timeline.map((item) => normalizeRecord(item)).filter((item) => item !== null)
            : [];
        timeline.splice(0, timeline.length, ...records);
        trimTimeline(stateMaxEntries);
    }
    catch {
        timeline.splice(0, timeline.length);
    }
}
export function configureDelegationRuntimeState(options) {
    persistenceEnabled = options.persistState;
    statePath = resolve(options.directory, options.stateFile);
    stateMaxEntries = Math.max(1, options.stateMaxEntries);
    loaded = false;
    load();
}
function delegationKey(sessionId, childRunId, traceId, subagentType) {
    const normalizedChildRunId = String(childRunId ?? "").trim();
    if (normalizedChildRunId) {
        return `${sessionId}:${normalizedChildRunId}`;
    }
    const normalizedTrace = String(traceId ?? "").trim();
    if (normalizedTrace) {
        return `${sessionId}:${normalizedTrace}`;
    }
    const normalizedSubagent = String(subagentType ?? "").trim().toLowerCase() || "unknown";
    return `${sessionId}:agent:${normalizedSubagent}`;
}
export function registerDelegationStart(input) {
    if (!input.sessionId.trim()) {
        return;
    }
    load();
    activeByDelegation.set(delegationKey(input.sessionId, input.childRunId, input.traceId, input.subagentType), {
        childRunId: input.childRunId,
        subagentType: input.subagentType,
        category: input.category,
        startedAt: input.startedAt,
        traceId: input.traceId,
    });
}
export function registerDelegationOutcome(input, maxEntries) {
    load();
    const directKey = delegationKey(input.sessionId, input.childRunId, input.traceId, input.subagentType);
    let active = activeByDelegation.get(directKey);
    let activeKey = directKey;
    if (!active && input.traceId) {
        const matches = [...activeByDelegation.entries()].filter(([candidateKey, candidate]) => (candidateKey === input.sessionId || candidateKey.startsWith(`${input.sessionId}:`)) &&
            candidate.traceId === input.traceId);
        if (matches.length === 1) {
            ;
            [[activeKey, active]] = matches;
        }
    }
    if (!active && !input.childRunId && !input.traceId && input.subagentType) {
        const matches = [...activeByDelegation.entries()].filter(([candidateKey, candidate]) => (candidateKey === input.sessionId || candidateKey.startsWith(`${input.sessionId}:`)) &&
            candidate.subagentType === input.subagentType);
        if (matches.length === 1) {
            ;
            [[activeKey, active]] = matches;
        }
    }
    if (!active && !input.childRunId && !input.traceId && !input.subagentType) {
        const matches = [...activeByDelegation.entries()].filter(([candidateKey]) => candidateKey === input.sessionId || candidateKey.startsWith(`${input.sessionId}:`));
        if (matches.length === 1) {
            ;
            [[activeKey, active]] = matches;
        }
    }
    if (!active) {
        return null;
    }
    activeByDelegation.delete(activeKey);
    const durationMs = Math.max(0, input.endedAt - active.startedAt);
    const record = {
        sessionId: input.sessionId,
        childRunId: active.childRunId,
        subagentType: active.subagentType,
        category: active.category,
        status: input.status,
        reasonCode: input.reasonCode ??
            (input.status === "failed"
                ? "delegation_runtime_failure"
                : "delegation_runtime_completed"),
        startedAt: active.startedAt,
        endedAt: input.endedAt,
        durationMs,
        traceId: active.traceId,
    };
    timeline.push(record);
    trimTimeline(Math.max(1, Math.min(maxEntries, stateMaxEntries)));
    persist();
    return record;
}
export function clearDelegationSession(sessionId) {
    for (const key of activeByDelegation.keys()) {
        if (key === sessionId || key.startsWith(`${sessionId}:`)) {
            activeByDelegation.delete(key);
        }
    }
}
export function getRecentDelegationOutcomes(windowMs) {
    load();
    const minTs = Date.now() - Math.max(0, windowMs);
    return timeline.filter((item) => item.endedAt >= minTs);
}
export function getDelegationFailureStats(windowMs) {
    const outcomes = getRecentDelegationOutcomes(windowMs);
    const total = outcomes.length;
    const failed = outcomes.filter((item) => item.status === "failed").length;
    return {
        total,
        failed,
        failureRate: total > 0 ? failed / total : 0,
    };
}
