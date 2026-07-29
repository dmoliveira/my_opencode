import { isProxy } from "node:util/types";
import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { createSecretRedactor, SecretRedactionError, } from "../shared/secret-redaction.js";
function messageSessionId(messages) {
    if (!Array.isArray(messages) || isProxy(messages)) {
        return "";
    }
    for (let index = 0; index < messages.length; index += 1) {
        const message = ownDataValue(messages, index);
        const info = ownDataValue(message, "info");
        const sessionID = ownDataValue(info, "sessionID");
        if (typeof sessionID === "string" && sessionID.trim()) {
            return sessionID;
        }
    }
    return "";
}
function ownDataValue(value, key) {
    if (!value || typeof value !== "object" || isProxy(value))
        return undefined;
    try {
        const descriptor = Object.getOwnPropertyDescriptor(value, key);
        return descriptor && "value" in descriptor ? descriptor.value : undefined;
    }
    catch {
        return undefined;
    }
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
function auditOpaqueAttachmentOmission(directory, surface, sessionId, stats) {
    if (stats.omittedOpaqueAttachmentMatches === 0)
        return;
    writeGatewayEventAudit(directory, {
        hook: "provider-boundary-secret-redactor",
        stage: "state",
        reason_code: "provider_boundary_opaque_attachment_collision_omitted",
        surface,
        session_id: sessionId,
        omitted_match_count: stats.omittedOpaqueAttachmentMatches,
    });
}
export function createProviderBoundarySecretFinalizer(options) {
    const redactor = createSecretRedactor(options);
    function blockAudit(directory, surface, sessionId, error) {
        const code = error instanceof SecretRedactionError ? error.code : "unexpected_failure";
        const matchDiagnostics = error instanceof SecretRedactionError && error.code === "immutable_match"
            ? {
                match_target: error.matchTarget,
                pattern_index: error.patternIndex,
                location_code: error.locationCode,
            }
            : {};
        writeGatewayEventAudit(directory, {
            hook: "provider-boundary-secret-redactor",
            stage: "guard",
            reason_code: "provider_boundary_secret_dispatch_blocked",
            surface,
            session_id: sessionId,
            error_code: code,
            ...matchDiagnostics,
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
                auditOpaqueAttachmentOmission(directory, "messages", sessionId, stats);
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
