import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
const activeByDelegation = new Map();
const timeline = [];
const policyProposals = [];
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
function normalizePolicyProposal(value) {
    if (!value || typeof value !== "object") {
        return null;
    }
    const source = value;
    const sessionId = String(source.sessionId ?? "").trim();
    const traceId = String(source.traceId ?? "").trim() || undefined;
    const subagentType = String(source.subagentType ?? "").trim();
    const originalCategory = String(source.originalCategory ?? "").trim();
    const proposedCategory = String(source.proposedCategory ?? "").trim();
    const mode = source.mode === "enforce" ? "enforce" : source.mode === "shadow" ? "shadow" : null;
    const failures = Number(source.failures ?? NaN);
    const samples = Number(source.samples ?? NaN);
    const failureRate = Number(source.failureRate ?? NaN);
    const createdAt = Number(source.createdAt ?? NaN);
    if (!sessionId ||
        !subagentType ||
        !originalCategory ||
        !proposedCategory ||
        !mode ||
        !Number.isFinite(failures) ||
        failures < 0 ||
        !Number.isFinite(samples) ||
        samples <= 0 ||
        failures > samples ||
        !Number.isFinite(failureRate) ||
        failureRate < 0 ||
        failureRate > 1 ||
        !Number.isFinite(createdAt)) {
        return null;
    }
    return {
        sessionId,
        traceId,
        subagentType,
        failures,
        samples,
        failureRate,
        originalCategory,
        proposedCategory,
        mode,
        applied: source.applied === true,
        createdAt,
    };
}
function trimPolicyProposals(maxEntries) {
    if (maxEntries <= 0) {
        policyProposals.splice(0, policyProposals.length);
        return;
    }
    while (policyProposals.length > maxEntries) {
        policyProposals.shift();
    }
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
    const payload = { timeline, policyProposals };
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
        const proposals = Array.isArray(parsed?.policyProposals)
            ? parsed.policyProposals
                .map((item) => normalizePolicyProposal(item))
                .filter((item) => item !== null)
            : [];
        timeline.splice(0, timeline.length, ...records);
        policyProposals.splice(0, policyProposals.length, ...proposals);
        trimTimeline(stateMaxEntries);
        trimPolicyProposals(stateMaxEntries);
    }
    catch {
        timeline.splice(0, timeline.length);
        policyProposals.splice(0, policyProposals.length);
    }
}
export function configureDelegationRuntimeState(options) {
    persistenceEnabled = options.persistState;
    statePath = resolve(options.directory, options.stateFile);
    stateMaxEntries = Math.max(1, options.stateMaxEntries);
    loaded = false;
    load();
}
function delegationKey(sessionId, childRunId) {
    const normalizedChildRunId = String(childRunId ?? "").trim();
    if (normalizedChildRunId) {
        return `${sessionId}:${normalizedChildRunId}`;
    }
    return "";
}
export function registerDelegationStart(input) {
    const childRunId = String(input.childRunId ?? "").trim();
    if (!input.sessionId.trim() || !childRunId) {
        return;
    }
    load();
    activeByDelegation.set(delegationKey(input.sessionId, childRunId), {
        childRunId,
        subagentType: input.subagentType,
        category: input.category,
        startedAt: input.startedAt,
        traceId: input.traceId,
    });
}
export function clearActiveDelegation(input) {
    load();
    const directKey = delegationKey(input.sessionId, input.childRunId);
    if (!directKey) {
        return false;
    }
    if (activeByDelegation.delete(directKey)) {
        return true;
    }
    return false;
}
export function registerDelegationOutcome(input, maxEntries) {
    load();
    const directKey = delegationKey(input.sessionId, input.childRunId);
    if (!directKey) {
        return null;
    }
    const active = activeByDelegation.get(directKey);
    if (!active) {
        return null;
    }
    activeByDelegation.delete(directKey);
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
export function registerDelegationPolicyProposal(input) {
    load();
    const record = normalizePolicyProposal(input);
    if (!record) {
        return null;
    }
    policyProposals.push(record);
    trimPolicyProposals(stateMaxEntries);
    persist();
    return record;
}
export function getRecentDelegationPolicyProposals(windowMs) {
    load();
    const minTs = Date.now() - Math.max(0, windowMs);
    return policyProposals.filter((item) => item.createdAt >= minTs);
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
