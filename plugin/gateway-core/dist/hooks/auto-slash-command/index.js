import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { buildCompactDecisionCacheKey, writeDecisionComparisonAudit, } from "../shared/llm-decision-runtime.js";
const AUTO_SLASH_COMMAND_TAG_OPEN = "<auto-slash-command>";
const AUTO_SLASH_COMMAND_TAG_CLOSE = "</auto-slash-command>";
const SLASH_COMMAND_PATTERN = /^\/([a-zA-Z][\w-]*)\s*(.*)/;
const EXCLUDED_COMMANDS = new Set(["ulw-loop"]);
const INLINE_SLASH_TOKEN_PATTERN = /(^|\s)\/([a-zA-Z][\w-]*)\b/g;
const HIGH_RISK_SKIP_PATTERN = /\b(install|npm\s+install|brew\s+install|setup|configure|deploy|production)\b/i;
const DETERMINISTIC_DOCTOR_PATTERN = /\b(doctor|diagnos(?:e|is|tic|tics))\b/i;
const DIAGNOSTIC_CUE_PATTERN = /\b(doctor|diagnos(?:e|is|tic|tics)|health(?:\s+check)?|debug|investigat(?:e|ion)|inspect)\b/i;
const ACTION_VERB_PATTERN = /\b(run|open|use|launch|start|check|perform|do|inspect|investigate|debug|review|analy[sz]e|look\s+into|tell\s+me|show\s+me|help\s+me\s+understand)\b/i;
const META_DISCUSSION_SKIP_PATTERN = /\b(last session|previous session|instruction command|prompt wording|prompt text|slash doctor|auto[-\s]?slash|why did|why does|routed to|route to|activated \/doctor|triggered \/doctor|command behavior|rewrite(?:s|d|ing)?|replac(?:e|es|ed|ing|ement)|convert(?:s|ed|ing)?|map(?:s|ped|ping)?|swap(?:s|ped|ping)?|chang(?:e|es|ed|ing))\b/i;
const REWRITE_CONTROL_PATTERN = /\b(disabl(?:e|ed|ing)|stop|prevent|remove|turn\s+off|keep)\b[\s\S]{0,80}\b(rewrite(?:s|d|ing)?|replac(?:e|es|ed|ing|ement)|convert(?:s|ed|ing)?|map(?:s|ped|ping)?|swap(?:s|ped|ping)?|chang(?:e|es|ed|ing))\b|\b(rewrite(?:s|d|ing)?|replac(?:e|es|ed|ing|ement)|convert(?:s|ed|ing)?|map(?:s|ped|ping)?|swap(?:s|ped|ping)?|chang(?:e|es|ed|ing))\b[\s\S]{0,80}\b(disabl(?:e|ed|ing)|stop|prevent|remove|turn\s+off|keep)\b/i;
const INVESTIGATION_CONTEXT_PATTERN = /\b(issue|environment|state|problem|wrong|error|failure|symptom|health)\b/i;
const AI_AUTO_SLASH_CHAR_TO_COMMAND = {
    D: "/doctor",
};
const LLM_DECISION_CHILD_ENV = "MY_OPENCODE_LLM_DECISION_CHILD";
// Removes fenced code blocks before slash-command detection.
function removeCodeBlocks(text) {
    return text.replace(/```[\s\S]*?```/g, "");
}
// Returns true when slash command is excluded from auto handling.
function isExcludedCommand(command) {
    return EXCLUDED_COMMANDS.has(command.toLowerCase());
}
// Parses an explicit slash command input.
function parseSlashCommand(text) {
    const trimmed = text.trim();
    if (!trimmed.startsWith("/")) {
        return null;
    }
    const match = trimmed.match(SLASH_COMMAND_PATTERN);
    if (!match) {
        return null;
    }
    const [, command, args] = match;
    const normalized = command.toLowerCase();
    if (isExcludedCommand(normalized)) {
        return null;
    }
    return {
        command: normalized,
        args: args.trim(),
        raw: trimmed,
    };
}
// Returns true when slash text targets an excluded command.
function isExcludedExplicitSlash(text) {
    INLINE_SLASH_TOKEN_PATTERN.lastIndex = 0;
    let match;
    while ((match = INLINE_SLASH_TOKEN_PATTERN.exec(text)) !== null) {
        const command = match[2]?.toLowerCase() ?? "";
        if (command && isExcludedCommand(command)) {
            return true;
        }
    }
    return false;
}
// Builds tagged injection payload for slash-command transformations.
function taggedSlashCommand(rawCommand) {
    return `${AUTO_SLASH_COMMAND_TAG_OPEN}\n${rawCommand}\n${AUTO_SLASH_COMMAND_TAG_CLOSE}`;
}
// Finds best text part index for slash command replacements.
function findSlashCommandPartIndex(parts) {
    for (let idx = 0; idx < parts.length; idx += 1) {
        const part = parts[idx];
        if (part.type !== "text") {
            continue;
        }
        if ((part.text ?? "").trim().startsWith("/")) {
            return idx;
        }
    }
    return parts.findIndex((part) => part.type === "text");
}
// Finds text part index that already contains explicit slash command text.
function findExplicitSlashPartIndex(parts) {
    for (let idx = 0; idx < parts.length; idx += 1) {
        const part = parts[idx];
        if (part.type !== "text") {
            continue;
        }
        if ((part.text ?? "").trim().startsWith("/")) {
            return idx;
        }
    }
    return -1;
}
// Extracts user prompt text from chat payload input/output variants.
function promptText(payload) {
    const props = payload.properties ?? {};
    const direct = [props.prompt, props.message, props.text];
    for (const candidate of direct) {
        if (typeof candidate === "string" && candidate.trim()) {
            return candidate.trim();
        }
    }
    const partSources = [payload.output?.parts, props.parts];
    for (const parts of partSources) {
        if (!Array.isArray(parts)) {
            continue;
        }
        const slashPart = parts.find((part) => part?.type === "text" && typeof part.text === "string" && part.text.trim().startsWith("/"));
        if (slashPart?.text?.trim()) {
            return slashPart.text.trim();
        }
        const text = parts
            .filter((part) => part?.type === "text" && typeof part.text === "string")
            .filter((part) => !part.synthetic)
            .map((part) => part.text?.trim() ?? "")
            .filter(Boolean)
            .join("\n");
        if (text) {
            return text;
        }
    }
    return "";
}
function resolveSessionId(payload) {
    const candidates = [
        payload.properties?.sessionID,
        payload.properties?.sessionId,
        payload.input?.sessionID,
        payload.input?.sessionId,
    ];
    for (const candidate of candidates) {
        if (typeof candidate === "string" && candidate.trim()) {
            return candidate.trim();
        }
    }
    return "";
}
function normalizePromptForAi(prompt) {
    const trimmed = prompt.trim();
    const actualRequestMatch = trimmed.match(/actual request\s*:\s*([\s\S]+)$/i);
    const extracted = actualRequestMatch?.[1]?.trim() || trimmed;
    return extracted
        .replace(/<[^>]+>/g, " ")
        .replace(/\b(user|assistant|system|tool)\s*:/gi, " ")
        .replace(/ignore all previous instructions/gi, " ")
        .replace(/ignore previous instructions/gi, " ")
        .replace(/answer\s+[A-Z]/g, " ")
        .replace(/force\s+no\s+slash/gi, " ")
        .replace(/\[tool-output\]/gi, " ")
        .replace(/\s+/g, " ")
        .trim();
}
// Maps natural language prompts to slash commands.
function detectSlash(prompt) {
    const cleaned = removeCodeBlocks(prompt);
    if (isExcludedExplicitSlash(cleaned)) {
        return { slash: null, excludedExplicit: true };
    }
    const explicit = parseSlashCommand(cleaned);
    if (explicit) {
        return { slash: explicit.raw, excludedExplicit: false };
    }
    const text = cleaned.toLowerCase();
    if (!META_DISCUSSION_SKIP_PATTERN.test(text) && DETERMINISTIC_DOCTOR_PATTERN.test(text) && ACTION_VERB_PATTERN.test(text)) {
        return { slash: "/doctor", excludedExplicit: false };
    }
    return { slash: null, excludedExplicit: false };
}
function shouldSkipAiAutoSlash(prompt) {
    const hasInvestigativeIntent = ACTION_VERB_PATTERN.test(prompt);
    const hasEligibleContext = DIAGNOSTIC_CUE_PATTERN.test(prompt) || INVESTIGATION_CONTEXT_PATTERN.test(prompt);
    return (HIGH_RISK_SKIP_PATTERN.test(prompt) ||
        META_DISCUSSION_SKIP_PATTERN.test(prompt) ||
        REWRITE_CONTROL_PATTERN.test(prompt) ||
        !hasInvestigativeIntent ||
        !hasEligibleContext);
}
function shouldSkipAutoSlash(prompt) {
    return HIGH_RISK_SKIP_PATTERN.test(prompt);
}
function buildAiSlashInstruction() {
    return "Classify only the sanitized user request text for explicit diagnostics intent. Return D only when the user is clearly asking to run or perform diagnostics or health checks now. Return N for meta discussion about prompts, routing, commands, past sessions, or instruction wording.";
}
function buildAiSlashContext(prompt) {
    return `request=${normalizePromptForAi(prompt) || "(empty)"}`;
}
function isLlmDecisionChildProcess() {
    return process.env[LLM_DECISION_CHILD_ENV] === "1";
}
// Creates auto slash command hook that rewrites prompt text when output parts are mutable.
export function createAutoSlashCommandHook(options) {
    return {
        id: "auto-slash-command",
        priority: 297,
        async event(type, payload) {
            if (!options.enabled || isLlmDecisionChildProcess()) {
                return;
            }
            if (type === "chat.message") {
                const eventPayload = (payload ?? {});
                const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                    ? eventPayload.directory
                    : options.directory;
                const sessionId = resolveSessionId(eventPayload);
                const prompt = promptText(eventPayload);
                if (!prompt) {
                    return;
                }
                if (shouldSkipAutoSlash(prompt)) {
                    return;
                }
                const detection = detectSlash(prompt);
                let slash = detection.slash;
                if (!slash && !detection.excludedExplicit && options.decisionRuntime && !shouldSkipAiAutoSlash(prompt)) {
                    let decision;
                    try {
                        decision = await options.decisionRuntime.decide({
                            hookId: "auto-slash-command",
                            sessionId,
                            templateId: "auto-slash-v1",
                            instruction: buildAiSlashInstruction(),
                            context: buildAiSlashContext(prompt),
                            userContext: prompt,
                            allowedChars: ["D", "N"],
                            decisionMeaning: {
                                D: "route_doctor",
                                N: "no_slash",
                            },
                            cacheKey: buildCompactDecisionCacheKey({
                                prefix: "auto-slash",
                                text: normalizePromptForAi(prompt),
                            }),
                        });
                    }
                    catch (error) {
                        writeGatewayEventAudit(directory, {
                            hook: "auto-slash-command",
                            stage: "skip",
                            reason_code: "llm_auto_slash_decision_failed",
                            session_id: sessionId,
                            llm_decision_mode: options.decisionRuntime.config.mode,
                            error: error instanceof Error ? error.message : String(error ?? "unknown_error"),
                        });
                        return;
                    }
                    if (decision.accepted) {
                        const aiSlash = AI_AUTO_SLASH_CHAR_TO_COMMAND[decision.char] ?? null;
                        writeDecisionComparisonAudit({
                            directory,
                            hookId: "auto-slash-command",
                            sessionId,
                            mode: options.decisionRuntime.config.mode,
                            deterministicMeaning: "no_slash",
                            aiMeaning: decision.meaning || (aiSlash ? "route_doctor" : "no_slash"),
                            deterministicValue: "none",
                            aiValue: aiSlash ?? "none",
                        });
                        const shadowDeferred = options.decisionRuntime.config.mode === "shadow" && aiSlash;
                        writeGatewayEventAudit(directory, {
                            hook: "auto-slash-command",
                            stage: "state",
                            reason_code: shadowDeferred
                                ? "llm_auto_slash_shadow_deferred"
                                : "llm_auto_slash_decision_recorded",
                            session_id: sessionId,
                            llm_decision_char: decision.char,
                            llm_decision_meaning: decision.meaning,
                            llm_decision_mode: options.decisionRuntime.config.mode,
                            slash_command: aiSlash ?? undefined,
                        });
                        if (shadowDeferred) {
                        }
                        else {
                            slash = aiSlash;
                        }
                    }
                }
                if (detection.excludedExplicit || !slash) {
                    return;
                }
                const parts = eventPayload.output?.parts;
                const idx = Array.isArray(parts) ? findSlashCommandPartIndex(parts) : -1;
                if (idx >= 0 && parts) {
                    parts[idx].text = taggedSlashCommand(slash);
                }
                else {
                    return;
                }
                writeGatewayEventAudit(directory, {
                    hook: "auto-slash-command",
                    stage: "state",
                    reason_code: "auto_slash_command_detected",
                    session_id: sessionId,
                    slash_command: slash,
                });
                return;
            }
            if (type !== "command.execute.before") {
                return;
            }
            const eventPayload = (payload ?? {});
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            const sessionId = resolveSessionId(eventPayload);
            const command = typeof eventPayload.input?.command === "string" ? eventPayload.input.command.trim() : "";
            const args = typeof eventPayload.input?.arguments === "string" && eventPayload.input.arguments.trim()
                ? eventPayload.input.arguments.trim()
                : "";
            if (!command || isExcludedCommand(command)) {
                return;
            }
            const raw = `/${command}${args ? ` ${args}` : ""}`;
            if (eventPayload.output && !Array.isArray(eventPayload.output.parts)) {
                eventPayload.output.parts = [];
            }
            const parts = eventPayload.output?.parts;
            const tagged = taggedSlashCommand(raw);
            const idx = Array.isArray(parts) ? findExplicitSlashPartIndex(parts) : -1;
            if (idx >= 0 && parts) {
                parts[idx].text = tagged;
            }
            else if (Array.isArray(parts)) {
                parts.unshift({ type: "text", text: tagged });
            }
            else {
                return;
            }
            writeGatewayEventAudit(directory, {
                hook: "auto-slash-command",
                stage: "state",
                reason_code: "auto_slash_command_detected",
                session_id: typeof sessionId === "string" ? sessionId : "",
                slash_command: raw,
            });
        },
    };
}
