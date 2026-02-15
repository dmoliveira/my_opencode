// Declares persisted gateway loop state for one active session.
export interface GatewayLoopState {
  active: boolean
  sessionId: string
  objective: string
  completionMode: "promise" | "objective"
  completionPromise: string
  iteration: number
  maxIterations: number
  startedAt: string
}

// Declares persisted gateway-wide runtime state shape.
export interface GatewayState {
  activeLoop: GatewayLoopState | null
  lastUpdatedAt: string
}
