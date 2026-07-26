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
}

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

  const explicitlyOrdered = new Set(order)
  const added = new Set<string>()
  const effectiveOrder: string[] = []
  for (const hookId of order) {
    if (disabledSet.has(hookId) || added.has(hookId)) {
      continue
    }
    const dependencies = HOOK_DEPENDENCIES[hookId] ?? []
    const disabledDependency = dependencies.find((dependencyId) =>
      disabledSet.has(dependencyId),
    )
    if (disabledDependency) {
      blocked.push({ hookId, dependencyId: disabledDependency })
      continue
    }
    for (const dependencyId of dependencies) {
      if (!explicitlyOrdered.has(dependencyId) && !added.has(dependencyId)) {
        effectiveOrder.push(dependencyId)
        added.add(dependencyId)
      }
    }
    effectiveOrder.push(hookId)
    added.add(hookId)
  }
  return {
    order: effectiveOrder,
    selected: new Set(effectiveOrder),
    blocked,
  }
}

/** Selects hooks for an event while retaining legacy wildcard compatibility. */
export function hooksForEvent(hooks: GatewayHook[], eventType: string): GatewayHook[] {
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
  return hooks
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
}
