// Declares hook handler contract for gateway events.
export interface GatewayHook {
  id: string
  priority: number
  /** Missing metadata preserves legacy dispatch to every event. */
  events?: readonly string[]
  event(type: string, payload: unknown): Promise<void>
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
