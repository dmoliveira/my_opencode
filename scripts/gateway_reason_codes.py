#!/usr/bin/env python3

from __future__ import annotations

# Canonical gateway runtime-mode reason codes shared by Python commands.
GATEWAY_PLUGIN_READY = "gateway_plugin_ready"
GATEWAY_PLUGIN_DISABLED = "gateway_plugin_disabled"
GATEWAY_PLUGIN_RUNTIME_UNAVAILABLE = "gateway_plugin_runtime_unavailable"
GATEWAY_PLUGIN_NOT_READY = "gateway_plugin_not_ready"

# Canonical gateway loop-state selection reason codes.
LOOP_STATE_AVAILABLE = "loop_state_available"
BRIDGE_STATE_IGNORED_IN_PLUGIN_MODE = "bridge_state_ignored_in_plugin_mode"
