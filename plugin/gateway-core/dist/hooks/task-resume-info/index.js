import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { writeDecisionComparisonAudit } from "../shared/llm-decision-runtime.js";
const RESUME_HINT = "Resume hint: keep the returned task_id and reuse it to continue the same subagent session.";
const CONTINUE_HINT = "Continuation hint: pending work remains; continue execution directly and avoid asking for extra confirmation turns.";
const VERIFICATION_HEADER = "Verification hint: review the subagent result before moving on.";
function extractResumeTarget(text) {
    const patterns = [
        /Session ID:\s*(ses_[a-zA-Z0-9]+)/,
        /session_id["':\s]+(ses_[a-zA-Z0-9]+)/i,
        /task_id["':\s]+([a-zA-Z0-9_-]+)/i,
        /\b(ses_[a-zA-Z0-9]+)\b/,
    ];
    for (const pattern of patterns) {
        const match = text.match(pattern);
        if (match?.[1]) {
            return match[1];
        }
    }
    return "";
}
function resolveSessionId(payload) {
    const candidates = [payload.input?.sessionID, payload.input?.sessionId];
    for (const candidate of candidates) {
        if (typeof candidate === "string" && candidate.trim()) {
            return candidate.trim();
        }
    }
    return "";
}
function buildSemanticHintInstruction(hasResumeTarget) {
    return hasResumeTarget
        ? "Classify whether this task result needs follow-up continuation and/or verification guidance. B=both continuation and verification, C=continuation only, V=verification only, N=none."
        : "Classify whether this task result still implies pending follow-up work that should continue in the same thread. C=continuation needed, N=no continuation.";
}
function buildSemanticHintContext(text, resumeTarget) {
    return [
        `resume_target=${resumeTarget || "(none)"}`,
        `task_output=${text.trim() || "(empty)"}`,
    ].join("\n");
}
async function resolveSemanticHints(options) {
    if (!options.sessionId || !options.decisionRuntime) {
        return { addContinuation: false, addVerification: false };
    }
    const hasResumeTarget = Boolean(options.resumeTarget);
    const allowedChars = hasResumeTarget ? ["B", "C", "V", "N"] : ["C", "N"];
    const decisionMeaning = hasResumeTarget
        ? {
            B: "continue_and_verify",
            C: "continue_only",
            V: "verify_only",
            N: "none",
        }
        : {
            C: "continue_only",
            N: "none",
        };
    const decision = await options.decisionRuntime.decide({
        hookId: "task-resume-info",
        sessionId: options.sessionId,
        templateId: hasResumeTarget ? "task-resume-info-v1" : "task-continue-info-v1",
        instruction: buildSemanticHintInstruction(hasResumeTarget),
        context: buildSemanticHintContext(options.text, options.resumeTarget),
        allowedChars,
        decisionMeaning,
        cacheKey: `task-resume-info:${hasResumeTarget ? options.resumeTarget : "none"}:${options.text.trim().toLowerCase()}`,
    });
    if (!decision.accepted) {
        return { addContinuation: false, addVerification: false };
    }
    const addContinuation = decision.char === "B" || decision.char === "C";
    const addVerification = hasResumeTarget && (decision.char === "B" || decision.char === "V");
    writeDecisionComparisonAudit({
        directory: options.directory,
        hookId: "task-resume-info",
        sessionId: options.sessionId,
        mode: options.decisionRuntime.config.mode,
        deterministicMeaning: "none",
        aiMeaning: decision.meaning || "none",
        deterministicValue: "none",
        aiValue: decision.char,
    });
    writeGatewayEventAudit(options.directory, {
        hook: "task-resume-info",
        stage: "state",
        reason_code: "llm_task_resume_decision_recorded",
        session_id: options.sessionId,
        llm_decision_char: decision.char,
        llm_decision_meaning: decision.meaning,
        llm_decision_mode: options.decisionRuntime.config.mode,
        resume_target: options.resumeTarget || undefined,
    });
    if (options.decisionRuntime.config.mode === "shadow" && (addContinuation || addVerification)) {
        writeGatewayEventAudit(options.directory, {
            hook: "task-resume-info",
            stage: "state",
            reason_code: "llm_task_resume_shadow_deferred",
            session_id: options.sessionId,
            llm_decision_char: decision.char,
            llm_decision_meaning: decision.meaning,
            llm_decision_mode: options.decisionRuntime.config.mode,
            resume_target: options.resumeTarget || undefined,
        });
        return { addContinuation: false, addVerification: false };
    }
    return { addContinuation, addVerification };
}
function buildVerificationHint(resumeTarget) {
    const retryLine = resumeTarget
        ? `If follow-up fixes are needed, use the canonical continuity flow (\`/plan-handoff resume\`, \`/resume-now\`, then \`/autopilot-resume\`) and reuse \`${resumeTarget}\` as the worker context reference.`
        : "If follow-up fixes are needed, use the canonical continuity flow (\`/plan-handoff resume\`, \`/resume-now\`, then \`/autopilot-resume\`) instead of spawning a brand new thread.";
    return [
        VERIFICATION_HEADER,
        "- Check the subagent's claimed changes and validation evidence before proceeding.",
        "- Reuse the returned worker context for fixes so investigation stays attached to the same thread.",
        `- ${retryLine}`,
    ].join("\n");
}
// Creates hook that appends resume hints after task tool responses.
export function createTaskResumeInfoHook(options) {
    return {
        id: "task-resume-info",
        priority: 340,
        async event(type, payload) {
            if (!options.enabled || type !== "tool.execute.after") {
                return;
            }
            const eventPayload = (payload ?? {});
            const tool = String(eventPayload.input?.tool ?? "").toLowerCase();
            if (tool !== "task") {
                return;
            }
            const output = eventPayload.output;
            if (!output || typeof output.output !== "string") {
                return;
            }
            const sessionId = resolveSessionId(eventPayload);
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : process.cwd();
            const text = output.output;
            let next = text;
            if (next.includes("task_id") && !next.includes(RESUME_HINT)) {
                next += `\n\n${RESUME_HINT}`;
            }
            if (next.includes("<CONTINUE-LOOP>") && !next.includes(CONTINUE_HINT)) {
                next += `\n\n${CONTINUE_HINT}`;
            }
            const resumeTarget = extractResumeTarget(next);
            if (!next.includes(CONTINUE_HINT) || (resumeTarget && !next.includes(VERIFICATION_HEADER))) {
                const semanticHints = await resolveSemanticHints({
                    text: next,
                    resumeTarget,
                    sessionId,
                    directory,
                    decisionRuntime: options.decisionRuntime,
                });
                if (semanticHints.addContinuation && !next.includes(CONTINUE_HINT)) {
                    next += `\n\n${CONTINUE_HINT}`;
                }
                if (semanticHints.addVerification && !next.includes(VERIFICATION_HEADER)) {
                    next += `\n\n${buildVerificationHint(resumeTarget)}`;
                }
            }
            if (resumeTarget && !next.includes(VERIFICATION_HEADER)) {
                next += `\n\n${buildVerificationHint(resumeTarget)}`;
            }
            output.output = next;
        },
    };
}
