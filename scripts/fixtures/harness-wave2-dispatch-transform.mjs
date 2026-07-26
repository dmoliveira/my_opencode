import GatewayCorePlugin from "../../plugin/gateway-core/dist/index.js"

const directory = process.env.WAVE2_DISPATCH_PROJECT
if (!directory) {
  throw new Error("WAVE2_DISPATCH_PROJECT is required")
}

const plugin = GatewayCorePlugin({ directory, config: {} })
await plugin["experimental.chat.messages.transform"](
  { sessionID: "wave2-baseline" },
  { messages: [] },
)
