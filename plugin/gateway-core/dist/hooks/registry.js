const HOOK_DEPENDENCIES = {
    continuation: ["stop-continuation-guard", "keyword-detector"],
    "global-process-pressure": ["stop-continuation-guard"],
    "todo-continuation-enforcer": ["stop-continuation-guard"],
};
/** Expands omitted stateful dependencies and excludes unsafe consumers. */
export function resolveHookConstructionPlan(order, disabled) {
    const disabledSet = new Set(disabled);
    const blocked = [];
    if (order.length === 0) {
        for (const [hookId, dependencies] of Object.entries(HOOK_DEPENDENCIES)) {
            if (disabledSet.has(hookId)) {
                continue;
            }
            for (const dependencyId of dependencies) {
                if (disabledSet.has(dependencyId)) {
                    blocked.push({ hookId, dependencyId });
                    break;
                }
            }
        }
        return { order: [], selected: null, blocked };
    }
    const explicitlyOrdered = new Set(order);
    const added = new Set();
    const effectiveOrder = [];
    for (const hookId of order) {
        if (disabledSet.has(hookId) || added.has(hookId)) {
            continue;
        }
        const dependencies = HOOK_DEPENDENCIES[hookId] ?? [];
        const disabledDependency = dependencies.find((dependencyId) => disabledSet.has(dependencyId));
        if (disabledDependency) {
            blocked.push({ hookId, dependencyId: disabledDependency });
            continue;
        }
        for (const dependencyId of dependencies) {
            if (!explicitlyOrdered.has(dependencyId) && !added.has(dependencyId)) {
                effectiveOrder.push(dependencyId);
                added.add(dependencyId);
            }
        }
        effectiveOrder.push(hookId);
        added.add(hookId);
    }
    return {
        order: effectiveOrder,
        selected: new Set(effectiveOrder),
        blocked,
    };
}
/** Selects hooks for an event while retaining legacy wildcard compatibility. */
export function hooksForEvent(hooks, eventType) {
    return hooks.filter((hook) => !hook.events || hook.events.includes(eventType));
}
// Resolves deterministic hook execution order.
export function resolveHookOrder(hooks, order, disabled) {
    const seenHookIds = new Set();
    const duplicateHookIds = new Set();
    for (const hook of hooks) {
        if (seenHookIds.has(hook.id)) {
            duplicateHookIds.add(hook.id);
        }
        seenHookIds.add(hook.id);
    }
    if (duplicateHookIds.size > 0) {
        throw new Error(`duplicate gateway hook ids: ${[...duplicateHookIds].sort().join(", ")}`);
    }
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
