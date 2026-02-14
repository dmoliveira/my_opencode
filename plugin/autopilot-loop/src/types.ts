// Declares supported completion modes for autopilot-loop.
export type CompletionMode = "promise" | "objective"

// Declares persisted loop state payload.
export interface AutopilotLoopState {
  active: boolean
  sessionId: string
  prompt: string
  iteration: number
  maxIterations: number
  completionMode: CompletionMode
  completionPromise: string
  startedAt: string
}

// Declares minimal assistant text part payload.
export interface TextPart {
  type: string
  text?: string
}

// Declares minimal session message payload used by detector.
export interface SessionMessage {
  info?: { role?: string }
  parts?: TextPart[]
}

// Declares minimal event payload shape used by hook runtime.
export interface HookEventPayload {
  event: {
    type: string
    properties?: Record<string, unknown>
  }
}

// Declares minimal OpenCode-like client API used by hook.
export interface HookClient {
  session: {
    messages(args: {
      path: { id: string }
      query?: { directory?: string }
    }): Promise<{ data?: SessionMessage[] }>
    promptAsync(args: {
      path: { id: string }
      body: { parts: Array<{ type: string; text: string }> }
      query?: { directory?: string }
    }): Promise<void>
  }
  tui?: {
    showToast(args: {
      body: {
        title: string
        message: string
        variant: "success" | "warning" | "info"
        duration: number
      }
    }): Promise<void>
  }
}

// Declares hook context required for runtime operations.
export interface HookContext {
  directory: string
  client: HookClient
}

// Declares hook creation options for integrations and testing.
export interface AutopilotLoopOptions {
  stateFile?: string
  apiTimeoutMs?: number
}
