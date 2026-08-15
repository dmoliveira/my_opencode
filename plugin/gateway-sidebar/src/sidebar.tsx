/** @jsxImportSource @opentui/solid */

import { watch, type FSWatcher } from "node:fs"
import { join } from "node:path"
import type { TextRenderable } from "@opentui/core"
import type { TuiPluginApi } from "@opencode-ai/plugin/tui"
import {
  EXECUTION_STATUS_DIRECTORY,
  EXECUTION_STATUS_FILE,
  readExecutionStatus,
  statusForSession,
  type ExecutionStatusSnapshot,
} from "./state-reader.js"

type ViewRefs = {
  goal?: TextRenderable
  last?: TextRenderable
  next?: TextRenderable
}

export function shouldBindStateDirectory(filename: string | Buffer | null | undefined): boolean {
  return (
    filename === null ||
    filename === undefined ||
    String(filename) === EXECUTION_STATUS_DIRECTORY
  )
}

export function shouldApplyRefresh(
  closed: boolean,
  generation: number,
  latestGeneration: number,
): boolean {
  return !closed && generation === latestGeneration
}

function displayText(value: unknown, fallback: string): string {
  if (typeof value !== "string") {
    return fallback
  }
  const compact = value.replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim()
  return compact ? compact.slice(0, 96) : fallback
}

// Connects the host's native renderer to a bounded, read-only status snapshot.
export function createExecutionStatusSidebar(api: TuiPluginApi) {
  let snapshot: ExecutionStatusSnapshot | null = null
  let rootWatcher: FSWatcher | undefined
  let stateWatcher: FSWatcher | undefined
  let timer: ReturnType<typeof setTimeout> | undefined
  let closed = false
  let refreshGeneration = 0
  const views = new Map<string, ViewRefs>()

  const updateView = (sessionId: string, refs = views.get(sessionId)): void => {
    if (!refs || closed) {
      return
    }
    const entry = statusForSession(snapshot, sessionId)
    if (refs.goal) {
      refs.goal.content = `Goal  ${displayText(api.state.session.get(sessionId)?.title, "Active execution")}`
    }
    if (refs.last) {
      refs.last.content = `Last  ${displayText(entry?.last, "No milestone yet")}`
    }
    if (refs.next) {
      refs.next.content = `Next  ${displayText(entry?.next, "Begin execution")}`
    }
    api.renderer.requestRender()
  }

  const updateAll = (): void => {
    for (const sessionId of views.keys()) {
      updateView(sessionId)
    }
  }

  const refresh = (): void => {
    const generation = ++refreshGeneration
    void readExecutionStatus(api.state.path.directory).then((value) => {
      if (!shouldApplyRefresh(closed, generation, refreshGeneration)) {
        return
      }
      snapshot = value
      updateAll()
    })
  }

  const schedule = (): void => {
    if (closed || timer) {
      return
    }
    timer = setTimeout(() => {
      timer = undefined
      refresh()
    }, 25)
  }

  const bindStateDirectory = (): void => {
    stateWatcher?.close()
    stateWatcher = undefined
    try {
      const stateDirectory = join(api.state.path.directory, EXECUTION_STATUS_DIRECTORY)
      stateWatcher = watch(stateDirectory, { persistent: false }, (_event, filename) => {
        const changed = String(filename ?? "")
        if (!changed || changed === EXECUTION_STATUS_FILE || changed.startsWith(`.${EXECUTION_STATUS_FILE}.`)) {
          schedule()
        }
      })
    } catch {
      // gateway-core creates .opencode lazily; the root watcher retries binding.
    }
  }

  try {
    rootWatcher = watch(api.state.path.directory, { persistent: false }, (_event, filename) => {
      if (shouldBindStateDirectory(filename)) {
        bindStateDirectory()
        schedule()
      }
    })
  } catch {
    // A workspace watcher must never prevent the sidebar from rendering.
  }
  const unsubscribeUpdated = api.event.on("session.updated", schedule)
  const unsubscribeIdle = api.event.on("session.idle", schedule)
  api.lifecycle.onDispose(() => {
    if (closed) {
      return
    }
    closed = true
    if (timer) {
      clearTimeout(timer)
    }
    rootWatcher?.close()
    stateWatcher?.close()
    unsubscribeUpdated()
    unsubscribeIdle()
    views.clear()
  })
  bindStateDirectory()
  refresh()

  const attach = (sessionId: string, key: keyof ViewRefs, node: TextRenderable): void => {
    const refs = views.get(sessionId) ?? {}
    refs[key] = node
    views.set(sessionId, refs)
    updateView(sessionId, refs)
  }

  const theme = () => api.theme.current
  return (props: { sessionId: string }) => (
    <box gap={1}>
      <text fg={theme().text}>
        <b>Execution</b>
      </text>
      <text
        fg={theme().textMuted}
        ref={(node: TextRenderable) => attach(props.sessionId, "goal", node)}
      >
        Goal  Active execution
      </text>
      <text
        fg={theme().textMuted}
        ref={(node: TextRenderable) => attach(props.sessionId, "last", node)}
      >
        Last  No milestone yet
      </text>
      <text
        fg={theme().textMuted}
        ref={(node: TextRenderable) => attach(props.sessionId, "next", node)}
      >
        Next  Begin execution
      </text>
    </box>
  )
}
