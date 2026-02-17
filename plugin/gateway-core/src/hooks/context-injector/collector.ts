interface ContextEntry {
  id: string
  source: string
  content: string
  priority: "critical" | "high" | "normal" | "low"
  timestamp: number
}

const PRIORITY_ORDER: Record<ContextEntry["priority"], number> = {
  critical: 0,
  high: 1,
  normal: 2,
  low: 3,
}

// Stores pending per-session context blocks that should be injected once.
export class ContextCollector {
  private sessions = new Map<string, Map<string, ContextEntry>>()

  // Resolves deterministic map key used for source:id de-duplication.
  private keyFor(options: { source: string; id?: string; content: string }): string {
    const source = options.source.trim()
    const id = typeof options.id === "string" ? options.id.trim() : ""
    if (id) {
      return JSON.stringify(["id", source, id])
    }
    return JSON.stringify(["content", source, options.content])
  }

  // Adds a context block for a session.
  register(
    sessionId: string,
    options: { source: string; id?: string; content: string; priority?: ContextEntry["priority"] },
  ): void {
    const normalizedSession = sessionId.trim()
    const normalizedSource = options.source.trim()
    const normalizedContent = options.content.trim()
    if (!normalizedSession || !normalizedSource || !normalizedContent) {
      return
    }
    const current = this.sessions.get(normalizedSession) ?? new Map<string, ContextEntry>()
    const key = this.keyFor({
      source: normalizedSource,
      id: options.id,
      content: normalizedContent,
    })
    current.set(key, {
      id: typeof options.id === "string" && options.id.trim() ? options.id.trim() : "",
      source: normalizedSource,
      content: normalizedContent,
      priority: options.priority ?? "normal",
      timestamp: Date.now(),
    })
    this.sessions.set(normalizedSession, current)
  }

  // Returns true when the session has pending injection content.
  hasPending(sessionId: string): boolean {
    const current = this.sessions.get(sessionId.trim())
    return current instanceof Map && current.size > 0
  }

  // Consumes pending session context and returns merged text.
  consume(sessionId: string): { hasContent: boolean; merged: string } {
    const normalizedSession = sessionId.trim()
    const current = this.sessions.get(normalizedSession)
    this.sessions.delete(normalizedSession)
    const entries = current ? [...current.values()] : []
    if (entries.length === 0) {
      return { hasContent: false, merged: "" }
    }
    const merged = entries
      .slice()
      .sort((a, b) => {
        const prioDiff = PRIORITY_ORDER[a.priority] - PRIORITY_ORDER[b.priority]
        if (prioDiff !== 0) {
          return prioDiff
        }
        return a.timestamp - b.timestamp
      })
      .map((entry) => entry.content)
      .join("\n\n---\n\n")
    return {
      hasContent: merged.trim().length > 0,
      merged,
    }
  }

  // Clears all pending session context.
  clear(sessionId: string): void {
    this.sessions.delete(sessionId.trim())
  }
}

export const contextCollector = new ContextCollector()
