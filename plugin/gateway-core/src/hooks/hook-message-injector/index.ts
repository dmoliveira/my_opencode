import { DEFAULT_INJECTED_TEXT_MAX_CHARS, truncateInjectedText } from "../shared/injected-text-truncator.js"

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

export interface HookMessageIdentity {
  agent?: string
  model?: { providerID: string; modelID: string; variant?: string }
}

// Resolves latest reusable agent/model identity from session history.
export async function resolveHookMessageIdentity(args: {
  session: SessionClient
  sessionId: string
  directory: string
}): Promise<HookMessageIdentity> {
  if (typeof args.session.messages !== "function") {
    return {}
  }

  try {
    const response = await args.session.messages({
      path: { id: args.sessionId },
      query: { directory: args.directory },
    })
    const messages = Array.isArray(response.data) ? response.data : []
    let agent: string | undefined
    let model: { providerID: string; modelID: string; variant?: string } | undefined

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
      if (agent && model) {
        break
      }
    }

    return {
      ...(agent ? { agent } : {}),
      ...(model ? { model } : {}),
    }
  } catch {
    return {}
  }
}

// Builds promptAsync body payload from content and optional identity.
export function buildHookMessageBody(content: string, identity: HookMessageIdentity): {
  parts: Array<{ type: string; text: string }>
  agent?: string
  model?: { providerID: string; modelID: string; variant?: string }
} {
  const normalized = content.trim()
  return {
    ...(identity.agent ? { agent: identity.agent } : {}),
    ...(identity.model ? { model: identity.model } : {}),
    parts: [{ type: "text", text: normalized }],
  }
}

// Injects synthetic hook content while preserving recent agent/model metadata.
export async function injectHookMessage(args: {
  session: SessionClient
  sessionId: string
  content: string
  directory: string
  maxChars?: number
}): Promise<boolean> {
  const maxChars =
    typeof args.maxChars === "number" && Number.isFinite(args.maxChars) && args.maxChars > 0
      ? Math.floor(args.maxChars)
      : DEFAULT_INJECTED_TEXT_MAX_CHARS
  const truncated = truncateInjectedText(args.content, maxChars)
  const content = truncated.text.trim()
  if (!content) {
    return false
  }

  const identity = await resolveHookMessageIdentity({
    session: args.session,
    sessionId: args.sessionId,
    directory: args.directory,
  })

  try {
    await args.session.promptAsync({
      path: { id: args.sessionId },
      body: buildHookMessageBody(content, identity),
      query: { directory: args.directory },
    })
    return true
  } catch {
    return false
  }
}
