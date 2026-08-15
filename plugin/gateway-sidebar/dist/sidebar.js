import { jsx as _jsx, jsxs as _jsxs } from "@opentui/solid/jsx-runtime";
/** @jsxImportSource @opentui/solid */
import { watch } from "node:fs";
import { join } from "node:path";
import { EXECUTION_STATUS_DIRECTORY, EXECUTION_STATUS_FILE, readExecutionStatus, statusForSession, } from "./state-reader.js";
export function shouldBindStateDirectory(filename) {
    return (filename === null ||
        filename === undefined ||
        String(filename) === EXECUTION_STATUS_DIRECTORY);
}
export function shouldApplyRefresh(closed, generation, latestGeneration) {
    return !closed && generation === latestGeneration;
}
function displayText(value, fallback) {
    if (typeof value !== "string") {
        return fallback;
    }
    const compact = value.replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim();
    return compact ? compact.slice(0, 96) : fallback;
}
// Connects the host's native renderer to a bounded, read-only status snapshot.
export function createExecutionStatusSidebar(api) {
    let snapshot = null;
    let rootWatcher;
    let stateWatcher;
    let timer;
    let closed = false;
    let refreshGeneration = 0;
    const views = new Map();
    const updateView = (sessionId, refs = views.get(sessionId)) => {
        if (!refs || closed) {
            return;
        }
        const entry = statusForSession(snapshot, sessionId);
        if (refs.goal) {
            refs.goal.content = `Goal  ${displayText(api.state.session.get(sessionId)?.title, "Active execution")}`;
        }
        if (refs.last) {
            refs.last.content = `Last  ${displayText(entry?.last, "No milestone yet")}`;
        }
        if (refs.next) {
            refs.next.content = `Next  ${displayText(entry?.next, "Begin execution")}`;
        }
        api.renderer.requestRender();
    };
    const updateAll = () => {
        for (const sessionId of views.keys()) {
            updateView(sessionId);
        }
    };
    const refresh = () => {
        const generation = ++refreshGeneration;
        void readExecutionStatus(api.state.path.directory).then((value) => {
            if (!shouldApplyRefresh(closed, generation, refreshGeneration)) {
                return;
            }
            snapshot = value;
            updateAll();
        });
    };
    const schedule = () => {
        if (closed || timer) {
            return;
        }
        timer = setTimeout(() => {
            timer = undefined;
            refresh();
        }, 25);
    };
    const bindStateDirectory = () => {
        stateWatcher?.close();
        stateWatcher = undefined;
        try {
            const stateDirectory = join(api.state.path.directory, EXECUTION_STATUS_DIRECTORY);
            stateWatcher = watch(stateDirectory, { persistent: false }, (_event, filename) => {
                const changed = String(filename ?? "");
                if (!changed || changed === EXECUTION_STATUS_FILE || changed.startsWith(`.${EXECUTION_STATUS_FILE}.`)) {
                    schedule();
                }
            });
        }
        catch {
            // gateway-core creates .opencode lazily; the root watcher retries binding.
        }
    };
    try {
        rootWatcher = watch(api.state.path.directory, { persistent: false }, (_event, filename) => {
            if (shouldBindStateDirectory(filename)) {
                bindStateDirectory();
                schedule();
            }
        });
    }
    catch {
        // A workspace watcher must never prevent the sidebar from rendering.
    }
    const unsubscribeUpdated = api.event.on("session.updated", schedule);
    const unsubscribeIdle = api.event.on("session.idle", schedule);
    api.lifecycle.onDispose(() => {
        if (closed) {
            return;
        }
        closed = true;
        if (timer) {
            clearTimeout(timer);
        }
        rootWatcher?.close();
        stateWatcher?.close();
        unsubscribeUpdated();
        unsubscribeIdle();
        views.clear();
    });
    bindStateDirectory();
    refresh();
    const attach = (sessionId, key, node) => {
        const refs = views.get(sessionId) ?? {};
        refs[key] = node;
        views.set(sessionId, refs);
        updateView(sessionId, refs);
    };
    const theme = () => api.theme.current;
    return (props) => (_jsxs("box", { gap: 1, children: [_jsx("text", { fg: theme().text, children: _jsx("b", { children: "Execution" }) }), _jsx("text", { fg: theme().textMuted, ref: (node) => attach(props.sessionId, "goal", node), children: "Goal  Active execution" }), _jsx("text", { fg: theme().textMuted, ref: (node) => attach(props.sessionId, "last", node), children: "Last  No milestone yet" }), _jsx("text", { fg: theme().textMuted, ref: (node) => attach(props.sessionId, "next", node), children: "Next  Begin execution" })] }));
}
