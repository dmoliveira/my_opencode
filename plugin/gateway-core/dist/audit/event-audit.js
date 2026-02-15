import { appendFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
// Returns true when gateway event auditing is enabled.
export function gatewayEventAuditEnabled() {
    const raw = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT ?? "";
    const value = raw.trim().toLowerCase();
    return value === "1" || value === "true" || value === "yes" || value === "on";
}
// Resolves gateway event audit file path.
export function gatewayEventAuditPath(directory) {
    const raw = process.env.MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH ?? "";
    if (raw.trim()) {
        return raw.trim();
    }
    return join(directory, ".opencode", "gateway-events.jsonl");
}
// Appends one sanitized gateway event audit entry.
export function writeGatewayEventAudit(directory, entry) {
    if (!gatewayEventAuditEnabled()) {
        return;
    }
    const path = gatewayEventAuditPath(directory);
    mkdirSync(dirname(path), { recursive: true });
    const payload = {
        ts: new Date().toISOString(),
        ...entry,
    };
    appendFileSync(path, `${JSON.stringify(payload)}\n`, "utf-8");
}
