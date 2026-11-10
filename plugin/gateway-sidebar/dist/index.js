import { jsx as _jsx } from "@opentui/solid/jsx-runtime";
import { createExecutionStatusSidebar } from "./sidebar.js";
const SUPPORTED_OPENCODE_VERSIONS = ["1.18.18", "1.18.33"];
const tui = async (api) => {
    if (!SUPPORTED_OPENCODE_VERSIONS.includes(api.app.version) || typeof api.slots?.register !== "function") {
        api.ui.toast({
            variant: "warning",
            title: "Execution sidebar disabled",
            message: `Requires OpenCode ${SUPPORTED_OPENCODE_VERSIONS.join(" or ")}; found ${api.app.version}.`,
        });
        return;
    }
    const View = createExecutionStatusSidebar(api);
    api.slots.register({
        order: 150,
        slots: {
            sidebar_content(_context, props) {
                return _jsx(View, { sessionId: props.session_id });
            },
        },
    });
};
export default {
    id: "my_opencode:gateway-sidebar",
    tui,
};
