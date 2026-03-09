import { spawn } from "node:child_process";
import { writeGatewayEventAudit } from "../../audit/event-audit.js";
export function resolveLlmDecisionRuntimeConfigForHook(config, hookId) {
    const override = config.hookModes[String(hookId ?? "").trim()] || config.hookModes[String(hookId ?? "").trim().toLowerCase()];
    if (!override || override === config.mode) {
        return config;
    }
    return {
        ...config,
        mode: override,
    };
}
function safePositiveInt(value, fallback) {
    return Number.isFinite(value) && value > 0 ? Math.floor(value) : fallback;
}
export function truncateDecisionText(text, maxChars) {
    const normalized = String(text ?? "").trim();
    if (!normalized) {
        return "";
    }
    if (normalized.length <= maxChars) {
        return normalized;
    }
    return `${normalized.slice(0, Math.max(0, maxChars - 16)).trimEnd()}\n[truncated]`;
}
export function buildSingleCharDecisionPrompt(request) {
    const compactContext = (request.context.trim() || "(empty)").replace(/\s+/g, " ").trim();
    return [
        `Return exactly one character from ${request.allowedChars.join(",")}.`,
        "No words, punctuation, or explanation.",
        `Task: ${request.instruction.trim()}`,
        `Context: ${compactContext}`,
        "Answer only.",
    ].join(" ");
}
export function parseSingleCharDecision(raw, allowedChars) {
    const allowed = new Set(allowedChars
        .map((item) => String(item ?? "").trim().toUpperCase())
        .filter((item) => item.length === 1));
    const normalized = String(raw ?? "")
        .replace(/\u0007/g, "")
        .trim()
        .toUpperCase();
    if (normalized.length !== 1) {
        return "";
    }
    return allowed.has(normalized) ? normalized : "";
}
function resolveDecisionMeaning(char, decisionMeaning) {
    const key = String(char || "").trim().toUpperCase();
    if (!key || !decisionMeaning) {
        return "";
    }
    const value = decisionMeaning[key];
    return typeof value === "string" ? value.trim() : "";
}
export function shouldAuditDecisionDisagreement(deterministicMeaning, aiMeaning) {
    const deterministic = deterministicMeaning.trim().toLowerCase();
    const ai = aiMeaning.trim().toLowerCase();
    return Boolean(deterministic && ai && deterministic !== ai);
}
export function writeDecisionComparisonAudit(input) {
    if (!shouldAuditDecisionDisagreement(input.deterministicMeaning, input.aiMeaning)) {
        return;
    }
    writeGatewayEventAudit(input.directory, {
        hook: input.hookId,
        stage: "state",
        reason_code: "llm_decision_disagreement",
        session_id: input.sessionId,
        trace_id: input.traceId,
        llm_decision_mode: input.mode,
        deterministic_decision_meaning: input.deterministicMeaning,
        deterministic_decision_value: input.deterministicValue,
        llm_decision_meaning: input.aiMeaning,
        llm_decision_value: input.aiValue,
    });
}
function pruneDecisionCache(cache, now, maxEntries) {
    for (const [key, value] of cache.entries()) {
        if (value.expiresAt <= now) {
            cache.delete(key);
        }
    }
    while (cache.size >= maxEntries && cache.size > 0) {
        let oldestKey = "";
        let oldestInsertedAt = Number.POSITIVE_INFINITY;
        for (const [key, value] of cache.entries()) {
            if (value.insertedAt < oldestInsertedAt) {
                oldestInsertedAt = value.insertedAt;
                oldestKey = key;
            }
        }
        if (!oldestKey) {
            return;
        }
        cache.delete(oldestKey);
    }
}
async function defaultRunner(args, timeoutMs, cwd) {
    return await new Promise((resolve, reject) => {
        const child = spawn(args[0] ?? "opencode", args.slice(1), {
            cwd,
            stdio: ["ignore", "pipe", "pipe"],
            env: {
                ...process.env,
                CI: process.env.CI ?? "true",
                GIT_TERMINAL_PROMPT: process.env.GIT_TERMINAL_PROMPT ?? "0",
                GIT_EDITOR: process.env.GIT_EDITOR ?? "true",
                GIT_PAGER: process.env.GIT_PAGER ?? "cat",
                PAGER: process.env.PAGER ?? "cat",
            },
        });
        let stdout = "";
        let stderr = "";
        let finished = false;
        const timer = setTimeout(() => {
            if (!finished) {
                child.kill("SIGTERM");
            }
        }, timeoutMs);
        child.stdout.on("data", (chunk) => {
            stdout += chunk.toString();
        });
        child.stderr.on("data", (chunk) => {
            stderr += chunk.toString();
        });
        child.on("error", (error) => {
            if (finished) {
                return;
            }
            finished = true;
            clearTimeout(timer);
            reject(error);
        });
        child.on("close", (code, signal) => {
            if (finished) {
                return;
            }
            finished = true;
            clearTimeout(timer);
            if (signal === "SIGTERM") {
                reject(new Error(`Timed out after ${timeoutMs}ms`));
                return;
            }
            if (code !== 0) {
                reject(new Error(stderr.trim() || `Command exited with code ${String(code)}`));
                return;
            }
            resolve({ stdout, stderr });
        });
    });
}
function extractTextFromJsonLines(stdout) {
    const chunks = [];
    for (const rawLine of stdout.split("\n")) {
        const line = rawLine.trim();
        if (!line || !line.startsWith("{")) {
            continue;
        }
        try {
            const parsed = JSON.parse(line);
            if (parsed.type === "text" && typeof parsed.part?.text === "string") {
                chunks.push(parsed.part.text);
            }
        }
        catch {
            continue;
        }
    }
    return chunks.join("\n").trim();
}
export function createLlmDecisionRuntime(options) {
    const runner = options.runner ?? defaultRunner;
    const config = {
        enabled: options.config.enabled,
        mode: options.config.mode,
        hookModes: options.config.hookModes ?? {},
        command: String(options.config.command || "opencode").trim() || "opencode",
        model: String(options.config.model || "openai/gpt-5.1-codex-mini").trim() || "openai/gpt-5.1-codex-mini",
        timeoutMs: safePositiveInt(options.config.timeoutMs, 30000),
        maxPromptChars: safePositiveInt(options.config.maxPromptChars, 1200),
        maxContextChars: safePositiveInt(options.config.maxContextChars, 2400),
        enableCache: Boolean(options.config.enableCache),
        cacheTtlMs: safePositiveInt(options.config.cacheTtlMs, 300000),
        maxCacheEntries: safePositiveInt(options.config.maxCacheEntries, 256),
    };
    const cache = new Map();
    return {
        config,
        async decide(request) {
            const start = Date.now();
            const baseResult = {
                mode: config.mode,
                accepted: false,
                char: "",
                raw: "",
                durationMs: 0,
                model: config.model,
                templateId: request.templateId,
            };
            const allowedChars = request.allowedChars
                .map((item) => String(item ?? "").trim().toUpperCase())
                .filter((item) => item.length === 1);
            if (!config.enabled || config.mode === "disabled") {
                return {
                    ...baseResult,
                    durationMs: Date.now() - start,
                    skippedReason: "runtime_disabled",
                };
            }
            if (!request.instruction.trim() || allowedChars.length === 0) {
                return {
                    ...baseResult,
                    durationMs: Date.now() - start,
                    skippedReason: "invalid_request",
                };
            }
            const prompt = buildSingleCharDecisionPrompt({
                instruction: truncateDecisionText(request.instruction, config.maxPromptChars),
                context: truncateDecisionText(request.context, config.maxContextChars),
                allowedChars,
            });
            const cacheKey = config.enableCache && typeof request.cacheKey === "string" && request.cacheKey.trim()
                ? `${config.model}:${request.templateId}:${request.cacheKey.trim()}`
                : "";
            if (cacheKey) {
                pruneDecisionCache(cache, Date.now(), config.maxCacheEntries);
                const cached = cache.get(cacheKey);
                if (cached && cached.expiresAt > Date.now()) {
                    writeGatewayEventAudit(options.directory, {
                        hook: request.hookId,
                        stage: "state",
                        reason_code: "llm_decision_cache_hit",
                        session_id: request.sessionId,
                        trace_id: request.traceId,
                        template_id: request.templateId,
                        decision_mode: config.mode,
                        model: config.model,
                        decision_char: cached.result.char || undefined,
                        decision_meaning: cached.result.meaning || undefined,
                    });
                    return {
                        ...cached.result,
                        cached: true,
                        durationMs: Date.now() - start,
                    };
                }
            }
            writeGatewayEventAudit(options.directory, {
                hook: request.hookId,
                stage: "state",
                reason_code: "llm_decision_requested",
                session_id: request.sessionId,
                trace_id: request.traceId,
                template_id: request.templateId,
                decision_mode: config.mode,
                model: config.model,
                allowed_chars: allowedChars.join(","),
            });
            try {
                const runArgs = [config.command, "run", "--model", config.model, "--format", "json", prompt];
                const response = await runner(runArgs, config.timeoutMs, options.directory);
                const raw = extractTextFromJsonLines(response.stdout);
                const char = parseSingleCharDecision(raw, allowedChars);
                const meaning = resolveDecisionMeaning(char, request.decisionMeaning);
                const durationMs = Date.now() - start;
                writeGatewayEventAudit(options.directory, {
                    hook: request.hookId,
                    stage: "state",
                    reason_code: char ? "llm_decision_accepted" : "llm_decision_invalid",
                    session_id: request.sessionId,
                    trace_id: request.traceId,
                    template_id: request.templateId,
                    decision_mode: config.mode,
                    model: config.model,
                    duration_ms: String(durationMs),
                    decision_char: char || undefined,
                    decision_meaning: meaning || undefined,
                });
                const result = {
                    ...baseResult,
                    accepted: Boolean(char),
                    char,
                    raw,
                    durationMs,
                    meaning: meaning || undefined,
                    skippedReason: char ? undefined : "invalid_response",
                };
                if (cacheKey && result.accepted) {
                    const now = Date.now();
                    pruneDecisionCache(cache, now, config.maxCacheEntries);
                    cache.set(cacheKey, {
                        insertedAt: now,
                        expiresAt: now + config.cacheTtlMs,
                        result: {
                            ...result,
                            cached: false,
                        },
                    });
                }
                return result;
            }
            catch (error) {
                const durationMs = Date.now() - start;
                const message = error instanceof Error ? error.message : String(error);
                writeGatewayEventAudit(options.directory, {
                    hook: request.hookId,
                    stage: "skip",
                    reason_code: "llm_decision_failed",
                    session_id: request.sessionId,
                    trace_id: request.traceId,
                    template_id: request.templateId,
                    decision_mode: config.mode,
                    model: config.model,
                    duration_ms: String(durationMs),
                });
                return {
                    ...baseResult,
                    durationMs,
                    error: message,
                    skippedReason: "runtime_error",
                };
            }
        },
    };
}
