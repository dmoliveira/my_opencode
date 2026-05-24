import { parseGatewayAuditJsonlWithDiagnostics } from "./llm-disagreement-report.js";
function normalized(value) {
    return String(value ?? "").trim().toLowerCase();
}
function latestIso(left, right) {
    const leftText = String(left ?? "").trim();
    const rightText = String(right ?? "").trim();
    if (!leftText) {
        return rightText || undefined;
    }
    if (!rightText) {
        return leftText;
    }
    return rightText.localeCompare(leftText) > 0 ? rightText : leftText;
}
function numeric(value) {
    return Number.isFinite(value) ? Number(value) : Number.parseInt(String(value ?? ""), 10) || 0;
}
function isTodoContinuationEvent(event) {
    const hook = normalized(event.hook);
    const reasonCode = normalized(event.reason_code);
    return (hook === "todo-continuation-enforcer" ||
        reasonCode.startsWith("todo_continuation_") ||
        reasonCode.startsWith("llm_todo_continuation_"));
}
function sortSessions(left, right) {
    return (String(right.lastTs ?? "").localeCompare(String(left.lastTs ?? "")) ||
        right.injected - left.injected ||
        right.todowriteSignals - left.todowriteSignals ||
        left.sessionId.localeCompare(right.sessionId));
}
export function buildTodoContinuationReport(events, options) {
    const reasonCounts = new Map();
    const sessionCounts = new Map();
    let totalEvents = 0;
    for (const event of events) {
        if (!isTodoContinuationEvent(event)) {
            continue;
        }
        totalEvents += 1;
        const reasonCode = normalized(event.reason_code) || "unknown";
        reasonCounts.set(reasonCode, (reasonCounts.get(reasonCode) ?? 0) + 1);
        const sessionId = String(event.session_id ?? "").trim();
        if (!sessionId) {
            continue;
        }
        const current = sessionCounts.get(sessionId) ?? {
            sessionId,
            injected: 0,
            todowriteSignals: 0,
            probeRetained: 0,
            stopGuards: 0,
            noPending: 0,
            probeFailures: 0,
            injectFailures: 0,
            llmDecisions: 0,
            llmShadows: 0,
            maxOpenTodoCount: 0,
        };
        current.lastTs = latestIso(current.lastTs, String(event.ts ?? ""));
        current.lastReasonCode = reasonCode;
        if (reasonCode === "todo_continuation_injected") {
            current.injected += 1;
        }
        if (reasonCode === "todo_continuation_todowrite_state_recorded") {
            current.todowriteSignals += 1;
            current.maxOpenTodoCount = Math.max(current.maxOpenTodoCount, numeric(event.open_todo_count));
        }
        if (reasonCode === "todo_continuation_task_probe_retained") {
            current.probeRetained += 1;
        }
        if (reasonCode === "todo_continuation_stop_guard") {
            current.stopGuards += 1;
        }
        if (reasonCode === "todo_continuation_no_pending") {
            current.noPending += 1;
        }
        if (reasonCode === "todo_continuation_probe_failed") {
            current.probeFailures += 1;
        }
        if (reasonCode === "todo_continuation_inject_failed") {
            current.injectFailures += 1;
        }
        if (reasonCode === "llm_todo_continuation_decision_recorded") {
            current.llmDecisions += 1;
        }
        if (reasonCode === "llm_todo_continuation_shadow_deferred") {
            current.llmShadows += 1;
        }
        sessionCounts.set(sessionId, current);
    }
    const sessionLimit = options?.sessionLimit;
    const sessions = [...sessionCounts.values()].sort(sortSessions);
    return {
        totalEvents,
        totalSessions: sessions.length,
        reasonCounts: [...reasonCounts.entries()]
            .map(([reasonCode, count]) => ({ reasonCode, count }))
            .sort((left, right) => right.count - left.count || left.reasonCode.localeCompare(right.reasonCode)),
        sessions: sessions.slice(0, sessionLimit && sessionLimit > 0 ? sessionLimit : 10),
        aggregateSignals: {
            probeFailures: sessions.reduce((sum, session) => sum + session.probeFailures, 0),
            injectFailures: sessions.reduce((sum, session) => sum + session.injectFailures, 0),
            stopGuards: sessions.reduce((sum, session) => sum + session.stopGuards, 0),
            maxOpenTodos: sessions.reduce((max, session) => Math.max(max, session.maxOpenTodoCount), 0),
        },
    };
}
export function parseTodoContinuationReport(text, options) {
    const parsed = parseGatewayAuditJsonlWithDiagnostics(text);
    return {
        report: buildTodoContinuationReport(parsed.events, options),
        invalidLines: parsed.invalidLines,
    };
}
function describeDegenerateTodoDistribution(report) {
    if (report.totalEvents === 0) {
        return [];
    }
    const insights = [];
    const topReason = report.reasonCounts[0];
    if (topReason && topReason.count === report.totalEvents) {
        insights.push(`- All continuation evidence is concentrated in one reason bucket: \`${topReason.reasonCode}\`.`);
    }
    const unknownCount = report.reasonCounts
        .filter((item) => item.reasonCode === "unknown")
        .reduce((sum, item) => sum + item.count, 0);
    if (unknownCount === report.totalEvents) {
        insights.push("- Every continuation event is labeled `unknown`; inspect the audit source before drawing workflow conclusions.");
    }
    else if (unknownCount > 0) {
        insights.push(`- Unknown reason codes account for ${unknownCount}/${report.totalEvents} continuation events; reason-count rankings are incomplete.`);
    }
    return insights;
}
function buildTodoFollowUps(report) {
    if (report.totalEvents === 0) {
        return [];
    }
    const followUps = [];
    const topReason = report.reasonCounts[0];
    const probeFailures = report.aggregateSignals?.probeFailures ?? 0;
    const injectFailures = report.aggregateSignals?.injectFailures ?? 0;
    const stopGuards = report.aggregateSignals?.stopGuards ?? 0;
    const maxOpenTodos = report.aggregateSignals?.maxOpenTodos ?? 0;
    if (topReason?.reasonCode === "todo_continuation_no_pending") {
        followUps.push("- Review whether the continuation check is firing after tasks were already closed; repeated `no_pending` events usually mean the prompt landed too late to help.");
    }
    if (topReason?.reasonCode === "todo_continuation_stop_guard" || stopGuards > 0) {
        followUps.push("- Inspect recent stop-guard sessions for messages that ended early without validation proof; these are the clearest candidates for follow-up prompt tuning.");
    }
    if (probeFailures > 0 || injectFailures > 0) {
        followUps.push(`- Investigate probe/injection failures first (${probeFailures} probe, ${injectFailures} inject); delivery gaps here can hide the true continuation rate.`);
    }
    if (maxOpenTodos >= 3) {
        followUps.push(`- Sessions peaked at ${maxOpenTodos} open todos; verify whether operators need a tighter summary or earlier reminder before the list grows.`);
    }
    if (followUps.length === 0 && topReason) {
        followUps.push(`- Start with the dominant reason bucket \`${topReason.reasonCode}\` and compare its latest sessions before changing the continuation policy.`);
    }
    return followUps;
}
export function renderTodoContinuationMarkdown(report) {
    const lines = [
        "# Todo Continuation Audit Report",
        "",
        ...(report.metadata?.generatedAt ? [`- Snapshot generated at: ${report.metadata.generatedAt}`] : []),
        ...(report.metadata?.branch ? [`- Branch: \`${report.metadata.branch}\``] : []),
        ...(report.metadata?.worktreePath ? [`- Worktree: \`${report.metadata.worktreePath}\``] : []),
        ...(report.metadata?.sourceAuditPath ? [`- Snapshot source audit: \`${report.metadata.sourceAuditPath}\``] : []),
        ...(report.metadata?.sourceAuditShared ? ["- Snapshot source scope: shared primary repo audit feed"] : []),
        ...(typeof report.metadata?.invalidLines === "number"
            ? [`- Invalid audit lines skipped: ${report.metadata.invalidLines}`]
            : []),
        ...(typeof report.metadata?.sessionLimit === "number"
            ? [`- Session snapshot rows requested: ${report.metadata.sessionLimit}`]
            : []),
        `- Total continuation events: ${report.totalEvents}`,
        `- Sessions with continuation evidence: ${report.totalSessions}`,
        "- Reason counts summarize audit events by continuation reason code.",
        "- Session rows show the latest retained snapshot per session, sorted by newest evidence.",
        ...(report.totalSessions > report.sessions.length
            ? [`- Session snapshot rows rendered: ${report.sessions.length}`]
            : []),
    ];
    const distributionInsights = describeDegenerateTodoDistribution(report);
    const followUps = buildTodoFollowUps(report);
    if (distributionInsights.length > 0) {
        lines.push("", "## Distribution insights", ...distributionInsights);
    }
    if (followUps.length > 0) {
        lines.push("", "## Operator follow-up", ...followUps);
    }
    lines.push("", "## Reason counts (event totals by continuation reason)");
    if (report.reasonCounts.length === 0) {
        lines.push("", "- No todo continuation audit events found.");
    }
    else {
        for (const item of report.reasonCounts) {
            lines.push("", `- ${item.reasonCode}: ${item.count}`);
        }
    }
    lines.push("", "## Session snapshots (latest evidence per session)");
    if (report.sessions.length === 0) {
        lines.push("", "- No continuation sessions found.");
    }
    else {
        for (const session of report.sessions) {
            const details = [
                `injected=${session.injected}`,
                `todowrite_signals=${session.todowriteSignals}`,
                `probe_retained=${session.probeRetained}`,
                `stop_guards=${session.stopGuards}`,
                `no_pending=${session.noPending}`,
            ];
            if (session.maxOpenTodoCount > 0) {
                details.push(`max_open_todos=${session.maxOpenTodoCount}`);
            }
            if (session.llmDecisions > 0 || session.llmShadows > 0) {
                details.push(`llm=${session.llmDecisions}`, `llm_shadow=${session.llmShadows}`);
            }
            if (session.probeFailures > 0 || session.injectFailures > 0) {
                details.push(`probe_failures=${session.probeFailures}`, `inject_failures=${session.injectFailures}`);
            }
            lines.push("", `- ${session.sessionId} (${session.lastTs ?? "unknown time"})`, `  - ${details.join(", ")}`, ...(session.lastReasonCode ? [`  - last_reason=${session.lastReasonCode}`] : []));
        }
    }
    return `${lines.join("\n")}\n`;
}
