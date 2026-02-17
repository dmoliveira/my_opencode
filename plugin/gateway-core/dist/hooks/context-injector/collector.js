const PRIORITY_ORDER = {
    critical: 0,
    high: 1,
    normal: 2,
    low: 3,
};
// Stores pending per-session context blocks that should be injected once.
export class ContextCollector {
    sessions = new Map();
    // Resolves deterministic map key used for source:id de-duplication.
    keyFor(options) {
        const source = options.source.trim();
        const id = typeof options.id === "string" ? options.id.trim() : "";
        if (id) {
            return JSON.stringify(["id", source, id]);
        }
        return JSON.stringify(["content", source, options.content]);
    }
    // Adds a context block for a session.
    register(sessionId, options) {
        const normalizedSession = sessionId.trim();
        const normalizedSource = options.source.trim();
        const normalizedContent = options.content.trim();
        if (!normalizedSession || !normalizedSource || !normalizedContent) {
            return;
        }
        const current = this.sessions.get(normalizedSession) ?? new Map();
        const key = this.keyFor({
            source: normalizedSource,
            id: options.id,
            content: normalizedContent,
        });
        current.set(key, {
            id: typeof options.id === "string" && options.id.trim() ? options.id.trim() : "",
            source: normalizedSource,
            content: normalizedContent,
            priority: options.priority ?? "normal",
            timestamp: Date.now(),
            metadata: options.metadata,
        });
        this.sessions.set(normalizedSession, current);
    }
    // Returns true when the session has pending injection content.
    hasPending(sessionId) {
        const current = this.sessions.get(sessionId.trim());
        return current instanceof Map && current.size > 0;
    }
    // Returns pending session context without clearing it.
    getPending(sessionId) {
        const normalizedSession = sessionId.trim();
        const current = this.sessions.get(normalizedSession);
        const entries = this.sortEntries(current ? [...current.values()] : []);
        if (entries.length === 0) {
            return { hasContent: false, merged: "", entries: [] };
        }
        const merged = entries.map((entry) => entry.content).join("\n\n---\n\n");
        return {
            hasContent: merged.trim().length > 0,
            merged,
            entries,
        };
    }
    // Consumes pending session context and returns merged text.
    consume(sessionId) {
        const normalizedSession = sessionId.trim();
        const pending = this.getPending(normalizedSession);
        this.sessions.delete(normalizedSession);
        return pending;
    }
    // Clears all pending session context.
    clear(sessionId) {
        this.sessions.delete(sessionId.trim());
    }
    // Sorts entries by priority, then insertion time.
    sortEntries(entries) {
        return entries.sort((a, b) => {
            const prioDiff = PRIORITY_ORDER[a.priority] - PRIORITY_ORDER[b.priority];
            if (prioDiff !== 0) {
                return prioDiff;
            }
            return a.timestamp - b.timestamp;
        });
    }
}
export const contextCollector = new ContextCollector();
