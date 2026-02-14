// Builds continuation prompt injected when session becomes idle.
export function buildContinuationPrompt(state) {
    const completionGuidance = state.completionMode === "objective"
        ? "When fully complete, emit <objective-complete>true</objective-complete>."
        : `When fully complete, emit <promise>${state.completionPromise}</promise>.`;
    return [
        `[AUTOPILOT LOOP ${state.iteration}/${state.maxIterations}]`,
        "Continue working on the current objective from where you stopped.",
        "Do not stop at planning only; execute concrete changes and validations.",
        completionGuidance,
        "Original objective:",
        state.prompt,
    ].join("\n\n");
}
