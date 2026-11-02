// Minimal structural contracts for the V2 hooks used here. Live smokes exercise
// these against the installed OpenCode SDK without bundling its runtime.
export interface Registration {
  dispose(): Promise<void>
}

export interface SessionHooks {
  hook(name: "context" | "compaction" | "generate" | "title", callback: (event: { system: unknown; messages: unknown }) => Promise<void>): Promise<Registration>
  hook(name: "http.request", callback: (event: { request: Request }) => Promise<void>): Promise<Registration>
  hook(name: "experimental.ws.send", callback: (event: { frame: string }) => Promise<void>): Promise<Registration>
}

export interface BeforeToolEvent {
  tool: string
  sessionID: string
  agent: string
  id: string
  input: unknown
}

export type AfterToolEvent =
  | { status: "completed"; result: unknown }
  | { status: "error"; error: unknown }

export interface ToolHooks {
  hook(name: "execute.before", callback: (event: BeforeToolEvent) => Promise<void>): Promise<Registration>
  hook(name: "execute.after", callback: (event: AfterToolEvent) => Promise<void>): Promise<Registration>
}
