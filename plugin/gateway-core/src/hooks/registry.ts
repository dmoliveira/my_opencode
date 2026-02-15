// Declares hook handler contract for gateway events.
export interface GatewayHook {
  id: string
  priority: number
  event(type: string, payload: unknown): Promise<void>
}

// Resolves deterministic hook execution order.
export function resolveHookOrder(
  hooks: GatewayHook[],
  order: string[],
  disabled: string[],
): GatewayHook[] {
  const disabledSet = new Set(disabled)
  const orderMap = new Map(order.map((id, idx) => [id, idx]))
  return hooks
    .filter((hook) => !disabledSet.has(hook.id))
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
