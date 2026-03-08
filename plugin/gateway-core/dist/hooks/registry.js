// Resolves deterministic hook execution order.
export function resolveHookOrder(hooks, order, disabled) {
    const disabledSet = new Set(disabled);
    const orderMap = new Map(order.map((id, idx) => [id, idx]));
    const explicitOrder = order.length > 0;
    return hooks
        .filter((hook) => !disabledSet.has(hook.id))
        .filter((hook) => !explicitOrder || orderMap.has(hook.id))
        .sort((a, b) => {
        const oa = orderMap.has(a.id) ? orderMap.get(a.id) : 10_000;
        const ob = orderMap.has(b.id) ? orderMap.get(b.id) : 10_000;
        if (oa !== ob) {
            return oa - ob;
        }
        if (a.priority !== b.priority) {
            return a.priority - b.priority;
        }
        return a.id.localeCompare(b.id);
    });
}
