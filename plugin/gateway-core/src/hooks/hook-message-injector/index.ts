interface SessionMessageInfo {
  role?: string
  agent?: string
  model?: { providerID?: string; modelID?: string; variant?: string }
  providerID?: string
  modelID?: string
}

interface SessionMessage {
  info?: SessionMessageInfo
}

interface SessionClient {
  messages?(args: {
    path: { id: string }
    query?: { directory?: string }
  }): Promise<{ data?: SessionMessage[] }>
  promptAsync(args: {
    path: { id: string }
    body: {
      parts: Array<{ type: string; text: string }>
      agent?: string
      model?: { providerID: string; modelID: string; variant?: string }
    }
    query?: { directory?: string }
  }): Promise<void>
}

// Injects synthetic hook content while preserving recent agent/model metadata.
export async function injectHookMessage(args: {
  session: SessionClient
  sessionId: string
  content: string
  directory: string
}): Promise<boolean> {
  const content = args.content.trim()
  if (!content) {
    return false
  }

  let agent: string | undefined
  let model: { providerID: string; modelID: string; variant?: string } | undefined
  if (typeof args.session.messages === "function") {
    try {
      const response = await args.session.messages({
        path: { id: args.sessionId },
        query: { directory: args.directory },
      })
    const messages = Array.isArray(response.data) ? response.data : []
    for (let idx = messages.length - 1; idx >= 0; idx -= 1) {
      const info = messages[idx]?.info
      if (!info || info.role === "assistant") {
        continue
      }
      if (!agent && typeof info.agent === "string" && info.agent.trim()) {
        agent = info.agent.trim()
      }
      if (!model) {
        if (info.model?.providerID && info.model?.modelID) {
          model = {
            providerID: info.model.providerID,
            modelID: info.model.modelID,
            ...(info.model.variant ? { variant: info.model.variant } : {}),
          }
        } else if (info.providerID && info.modelID) {
          model = {
            providerID: info.providerID,
            modelID: info.modelID,
          }
        }
      }
      if (agent || model) {
        break
      }
    }
    } catch {
      // best-effort metadata resolution
    }
  }

  try {
    await args.session.promptAsync({
      path: { id: args.sessionId },
      body: {
        ...(agent ? { agent } : {}),
        ...(model ? { model } : {}),
        parts: [{ type: "text", text: content }],
      },
      query: { directory: args.directory },
    })
    return true
  } catch {
    return false
  }
}
