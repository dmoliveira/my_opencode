import { watch, type FSWatcher } from "node:fs"
import { join } from "node:path"
import {
  EXECUTION_STATUS_DIRECTORY,
  EXECUTION_STATUS_FILE,
  readExecutionStatus,
  type ExecutionStatusSnapshot,
} from "../../gateway-sidebar/src/state-reader.ts"

// One watcher belongs to one rendered session location and never writes state.
export function watchExecutionStatus(
  directory: string,
  update: (snapshot: ExecutionStatusSnapshot | null) => void,
): () => void {
  let rootWatcher: FSWatcher | undefined
  let stateWatcher: FSWatcher | undefined
  let timer: ReturnType<typeof setTimeout> | undefined
  let closed = false
  let generation = 0

  const refresh = () => {
    const current = ++generation
    void readExecutionStatus(directory).then((snapshot) => {
      if (!closed && current === generation) update(snapshot)
    }).catch(() => {
      if (!closed && current === generation) update(null)
    })
  }
  const schedule = () => {
    if (closed || timer) return
    timer = setTimeout(() => {
      timer = undefined
      refresh()
    }, 25)
  }
  const bind = () => {
    if (closed) return
    stateWatcher?.close()
    stateWatcher = undefined
    try {
      stateWatcher = watch(join(directory, EXECUTION_STATUS_DIRECTORY), { persistent: false }, (_event, filename) => {
        const changed = String(filename ?? "")
        if (!changed || changed === EXECUTION_STATUS_FILE || changed.startsWith(`.${EXECUTION_STATUS_FILE}.`)) schedule()
      })
      stateWatcher.on("error", () => {})
    } catch {
      // The gateway may create its state directory after the view opens.
    }
  }
  try {
    rootWatcher = watch(directory, { persistent: false }, (_event, filename) => {
      if (!closed && (filename == null || String(filename) === EXECUTION_STATUS_DIRECTORY)) {
        bind()
        schedule()
      }
    })
    rootWatcher.on("error", () => {})
  } catch {
    // A missing or inaccessible workspace must not prevent the TUI loading.
  }
  bind()
  refresh()
  return () => {
    if (closed) return
    closed = true
    if (timer) clearTimeout(timer)
    rootWatcher?.close()
    stateWatcher?.close()
  }
}
