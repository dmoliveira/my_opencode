// Declares persisted gateway loop state for one active session.
export interface GatewayLoopState {
  active: boolean
  sessionId: string
  objective: string
  doneCriteria?: string[]
  ignoredCompletionCycles?: number
  completionMode: "promise" | "objective"
  completionPromise: string
  iteration: number
  maxIterations: number
  startedAt: string
}

export interface GatewayConciseModeState {
  mode: "off" | "lite" | "full" | "ultra" | "review" | "commit"
  source: string
  sessionId: string
  activatedAt: string
  updatedAt: string
}

// Declares persisted gateway-wide runtime state shape.
export interface GatewayState {
  activeLoop: GatewayLoopState | null
  conciseMode?: GatewayConciseModeState | null
  lastUpdatedAt: string
  source?: string
}
