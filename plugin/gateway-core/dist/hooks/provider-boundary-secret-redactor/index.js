import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { createSecretRedactor, SecretRedactionError, } from "../shared/secret-redaction.js";
function messageSessionId(messages) {
    if (!Array.isArray(messages)) {
        return "";
    }
    for (const message of messages) {
        if (!message || typeof message !== "object") {
            continue;
        }
        const info = message.info;
        if (!info || typeof info !== "object") {
            continue;
        }
        const sessionID = info.sessionID;
        if (typeof sessionID === "string" && sessionID.trim()) {
            return sessionID;
        }
    }
    return "";
}
function auditRedaction(directory, surface, sessionId, stats) {
    if (stats.matches === 0) {
        return;
    }
    writeGatewayEventAudit(directory, {
        hook: "provider-boundary-secret-redactor",
        stage: "state",
        reason_code: "provider_boundary_secrets_redacted",
        surface,
        session_id: sessionId,
        match_count: stats.matches,
        redacted_field_count: stats.redactedFields,
        scanned_chars: stats.scannedChars,
        scanned_nodes: stats.scannedNodes,
    });
}
export function createProviderBoundarySecretFinalizer(options) {
    const redactor = createSecretRedactor(options);
    function blockAudit(directory, surface, sessionId, error) {
        const code = error instanceof SecretRedactionError ? error.code : "unexpected_failure";
        writeGatewayEventAudit(directory, {
            hook: "provider-boundary-secret-redactor",
            stage: "guard",
            reason_code: "provider_boundary_secret_dispatch_blocked",
            surface,
            session_id: sessionId,
            error_code: code,
        });
        if (error instanceof SecretRedactionError) {
            throw error;
        }
        throw new SecretRedactionError("unexpected_failure");
    }
    return {
        finalizeMessages(payload) {
            const messages = payload.output?.messages;
            if (!Array.isArray(messages)) {
                return;
            }
            const directory = payload.directory?.trim() || options.directory;
            const sessionId = payload.input?.sessionID?.trim() || messageSessionId(messages);
            try {
                const stats = redactor.redactProviderMessages(messages);
                auditRedaction(directory, "messages", sessionId, stats);
            }
            catch (error) {
                blockAudit(directory, "messages", sessionId, error);
            }
        },
        finalizeSystem(payload) {
            const system = payload.output?.system;
            if (!Array.isArray(system)) {
                return;
            }
            const directory = payload.directory?.trim() || options.directory;
            const sessionId = payload.input?.sessionID?.trim() || "";
            try {
                const stats = redactor.redactProviderSystem(system);
                auditRedaction(directory, "system", sessionId, stats);
            }
            catch (error) {
                blockAudit(directory, "system", sessionId, error);
            }
        },
    };
}
