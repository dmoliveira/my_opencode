/** @jsxImportSource @opentui/solid */

import { isAbsolute } from "node:path"
import { Plugin } from "@opencode/plugin/tui"
import type { Context } from "@opencode/plugin/tui/context"
import { createEffect, createSignal, onCleanup } from "solid-js"
import {
  statusForSession,
  type ExecutionStatusSnapshot,
} from "../../gateway-sidebar/src/state-reader.ts"
import { watchExecutionStatus } from "./status-watcher.ts"

const SUPPORTED_OPENCODE_VERSIONS: ReadonlySet<string> = new Set(["2.2.6", "2.3.2"])

function displayText(value: unknown, fallback: string): string {
  if (typeof value !== "string") return fallback
  const text = value.replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim()
  return text ? text.slice(0, 96) : fallback
}

function ExecutionView(props: { context: Context; sessionID: string }) {
  const [snapshot, setSnapshot] = createSignal<ExecutionStatusSnapshot | null>(null)
  const session = () => props.context.data.session.get(props.sessionID)

  createEffect(() => {
    const directory = session()?.location.directory
    setSnapshot(null)
    if (!directory || !isAbsolute(directory)) return
    onCleanup(watchExecutionStatus(directory, setSnapshot))
  })

  const status = () => statusForSession(snapshot(), props.sessionID)
  return (
    <box gap={1}>
      <text fg={props.context.theme.text.base}><b>Execution</b></text>
      <text fg={props.context.theme.text.muted}>Goal  {displayText(session()?.title, "Active execution")}</text>
      <text fg={props.context.theme.text.muted}>Last  {displayText(status()?.last, "No milestone yet")}</text>
      <text fg={props.context.theme.text.muted}>Next  {displayText(status()?.next, "Begin execution")}</text>
    </box>
  )
}

export default Plugin.define({
  id: "my_opencode.gateway-sidebar-v2",
  setup(context) {
    if (!SUPPORTED_OPENCODE_VERSIONS.has(context.app.version)) {
      context.ui.toast.show({
        variant: "warning",
        message: `Execution sidebar requires OpenCode ${[...SUPPORTED_OPENCODE_VERSIONS].join(" or ")}; found ${context.app.version}.`,
      })
      return
    }
    return context.ui.slot({
      append: "sidebar.content",
      render: (input) => <ExecutionView context={context} sessionID={input.sessionID} />,
    })
  },
})
