interface ContextEntry {
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
  private sessions = new Map<string, ContextEntry[]>()

  // Adds a context block for a session.
  register(
    sessionId: string,
    options: { source: string; content: string; priority?: ContextEntry["priority"] },
  ): void {
    const normalizedSession = sessionId.trim()
    const normalizedContent = options.content.trim()
    if (!normalizedSession || !normalizedContent) {
      return
    }
    const current = this.sessions.get(normalizedSession) ?? []
    current.push({
      source: options.source,
      content: normalizedContent,
      priority: options.priority ?? "normal",
      timestamp: Date.now(),
    })
    this.sessions.set(normalizedSession, current)
  }

  // Returns true when the session has pending injection content.
  hasPending(sessionId: string): boolean {
    const current = this.sessions.get(sessionId.trim())
    return Array.isArray(current) && current.length > 0
  }

  // Consumes pending session context and returns merged text.
  consume(sessionId: string): { hasContent: boolean; merged: string } {
    const normalizedSession = sessionId.trim()
    const current = this.sessions.get(normalizedSession) ?? []
    this.sessions.delete(normalizedSession)
    if (current.length === 0) {
      return { hasContent: false, merged: "" }
    }
    const merged = current
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
