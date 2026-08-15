// Declares persisted gateway loop state for one active session.
export interface GatewayLoopState {
  [key: string]: unknown
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
  [key: string]: unknown
  mode: "off" | "lite" | "full" | "ultra" | "review" | "commit"
  source: string
  sessionId: string
  activatedAt: string
  updatedAt: string
}

// Declares one privacy-safe execution milestone for a TUI session.
export interface GatewayExecutionStatusEntry {
  [key: string]: unknown
  sessionId: string
  last: string
  next: string
  updatedAt: string
}

// Declares the bounded execution-status state consumed by the TUI sidebar.
export interface GatewayExecutionStatusState {
  [key: string]: unknown
  version: 1
  sessions: Record<string, GatewayExecutionStatusEntry>
}

// Declares persisted gateway-wide runtime state shape.
export interface GatewayState {
  [key: string]: unknown
  activeLoop: GatewayLoopState | null
  conciseMode?: GatewayConciseModeState | null
  executionStatus?: GatewayExecutionStatusState | null
  lastUpdatedAt: string
  source?: string
}
