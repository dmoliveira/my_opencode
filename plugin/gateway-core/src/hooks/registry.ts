import { DEFAULT_GATEWAY_HOOK_ORDER } from "../config/schema.js"

// Declares hook handler contract for gateway events.
export interface GatewayHook {
  id: string
  priority: number
  /** Missing metadata preserves legacy dispatch to every event. */
  events?: readonly string[]
  event(type: string, payload: unknown): Promise<void>
}

const HOOK_DEPENDENCIES: Readonly<Record<string, readonly string[]>> = {
  continuation: ["stop-continuation-guard", "keyword-detector"],
  "global-process-pressure": ["stop-continuation-guard"],
  "todo-continuation-enforcer": ["stop-continuation-guard"],
  "done-proof-enforcer": ["validation-evidence-ledger"],
  "pr-readiness-guard": ["validation-evidence-ledger"],
  "pr-body-evidence-guard": ["validation-evidence-ledger"],
}

export function validateHookDependencyGraph(
  dependencies: Readonly<Record<string, readonly string[]>> = HOOK_DEPENDENCIES,
  knownHookIds: readonly string[] = DEFAULT_GATEWAY_HOOK_ORDER,
): void {
  const known = new Set(knownHookIds)
  if (known.size !== knownHookIds.length) {
    throw new Error("duplicate gateway hook id in canonical manifest")
  }
  for (const [hookId, hookDependencies] of Object.entries(dependencies)) {
    if (!known.has(hookId)) {
      throw new Error(`unknown gateway hook dependency consumer: ${hookId}`)
    }
    const seen = new Set<string>()
    for (const dependencyId of hookDependencies) {
      if (!known.has(dependencyId)) {
        throw new Error(
          `unknown gateway hook dependency endpoint: ${hookId} -> ${dependencyId}`,
        )
      }
      if (seen.has(dependencyId)) {
        throw new Error(
          `duplicate gateway hook dependency endpoint: ${hookId} -> ${dependencyId}`,
        )
      }
      seen.add(dependencyId)
    }
  }

  const visiting = new Set<string>()
  const visited = new Set<string>()
  const visit = (hookId: string): void => {
    if (visited.has(hookId)) {
      return
    }
    if (visiting.has(hookId)) {
      throw new Error(`gateway hook dependency cycle detected at: ${hookId}`)
    }
    visiting.add(hookId)
    for (const dependencyId of dependencies[hookId] ?? []) {
      visit(dependencyId)
    }
    visiting.delete(hookId)
    visited.add(hookId)
  }
  for (const hookId of Object.keys(dependencies)) {
    visit(hookId)
  }
}

validateHookDependencyGraph()

export interface HookDependencyBlock {
  hookId: string
  dependencyId: string
}

export interface HookConstructionPlan {
  order: string[]
  selected: ReadonlySet<string> | null
  blocked: HookDependencyBlock[]
}

/** Expands omitted stateful dependencies and excludes unsafe consumers. */
export function resolveHookConstructionPlan(
  order: string[],
  disabled: string[],
): HookConstructionPlan {
  const disabledSet = new Set(disabled)
  const blocked: HookDependencyBlock[] = []

  if (order.length === 0) {
    for (const [hookId, dependencies] of Object.entries(HOOK_DEPENDENCIES)) {
      if (disabledSet.has(hookId)) {
        continue
      }
      for (const dependencyId of dependencies) {
        if (disabledSet.has(dependencyId)) {
          blocked.push({ hookId, dependencyId })
          break
        }
      }
    }
    return { order: [], selected: null, blocked }
  }

  const added = new Set<string>()
  const unavailable = new Set<string>()
  const effectiveOrder: string[] = []
  const blockedKeys = new Set<string>()
  const block = (hookId: string, dependencyId: string): void => {
    const key = `${hookId}\u0000${dependencyId}`
    if (!blockedKeys.has(key)) {
      blocked.push({ hookId, dependencyId })
      blockedKeys.add(key)
    }
    unavailable.add(hookId)
  }
  const addWithDependencies = (hookId: string): boolean => {
    if (added.has(hookId)) {
      return true
    }
    if (disabledSet.has(hookId) || unavailable.has(hookId)) {
      return false
    }
    const dependencies = HOOK_DEPENDENCIES[hookId] ?? []
    const disabledDependency = dependencies.find((dependencyId) =>
      disabledSet.has(dependencyId),
    )
    if (disabledDependency) {
      block(hookId, disabledDependency)
      return false
    }
    for (const dependencyId of dependencies) {
      if (!addWithDependencies(dependencyId)) {
        block(hookId, dependencyId)
        return false
      }
    }
    effectiveOrder.push(hookId)
    added.add(hookId)
    return true
  }
  for (const hookId of order) {
    addWithDependencies(hookId)
  }
  return {
    order: effectiveOrder,
    selected: new Set(effectiveOrder),
    blocked,
  }
}

/** Selects hooks for an event while retaining legacy wildcard compatibility. */
export function hooksForEvent(
  hooks: GatewayHook[],
  eventType: string,
): GatewayHook[] {
  return hooks.filter((hook) => !hook.events || hook.events.includes(eventType))
}

// Resolves deterministic hook execution order.
export function resolveHookOrder(
  hooks: GatewayHook[],
  order: string[],
  disabled: string[],
): GatewayHook[] {
  const seenHookIds = new Set<string>()
  const duplicateHookIds = new Set<string>()
  for (const hook of hooks) {
    if (seenHookIds.has(hook.id)) {
      duplicateHookIds.add(hook.id)
    }
    seenHookIds.add(hook.id)
  }
  if (duplicateHookIds.size > 0) {
    throw new Error(
      `duplicate gateway hook ids: ${[...duplicateHookIds].sort().join(", ")}`,
    )
  }
  const disabledSet = new Set(disabled)
  const orderMap = new Map(order.map((id, idx) => [id, idx]))
  const explicitOrder = order.length > 0
  const baseline = hooks
    .filter((hook) => !disabledSet.has(hook.id))
    .filter((hook) => !explicitOrder || orderMap.has(hook.id))
    .sort((a, b) => {
      const oa = orderMap.has(a.id) ? (orderMap.get(a.id) as number) : 10_000
      const ob = orderMap.has(b.id) ? (orderMap.get(b.id) as number) : 10_000
      if (oa !== ob) {
        return oa - ob
      }
      if (a.priority !== b.priority) {
        return a.priority - b.priority
      }
      return a.id.localeCompare(b.id)
    })
  if (explicitOrder) {
    return baseline
  }

  const hookById = new Map(baseline.map((hook) => [hook.id, hook]))
  const added = new Set<string>()
  const effectiveOrder: GatewayHook[] = []
  const addWithDependencies = (hook: GatewayHook): void => {
    if (added.has(hook.id)) {
      return
    }
    for (const dependencyId of HOOK_DEPENDENCIES[hook.id] ?? []) {
      const dependency = hookById.get(dependencyId)
      if (dependency) {
        addWithDependencies(dependency)
      }
    }
    effectiveOrder.push(hook)
    added.add(hook.id)
  }
  for (const hook of baseline) {
    addWithDependencies(hook)
  }
  return effectiveOrder
}
