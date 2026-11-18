// Words for the monitoring board, shared by the board, its table view and the live feed.

import type { GateKey, MonitorState } from "@/services/hub";

export const GATE_ORDER: GateKey[] = ["key", "privacy", "permissions", "limits"];

export const GATES: Record<GateKey, { name: string; icon: string; help: string }> = {
  key: { name: "Key", icon: "key",
         help: "The client key must be valid: not revoked, not expired, and its app and access profile switched on." },
  privacy: { name: "Privacy", icon: "eye-off",
             help: "Inputs that are malformed, carry personal data (emails, phone or ID numbers) or try to set fields the AI may not set, such as user_id or role, are refused." },
  permissions: { name: "Permissions", icon: "lock",
                 help: "The tool must be published and switched on, its data source allowed, the key allowed to use it and the signed-in user's token valid." },
  limits: { name: "Limits", icon: "clock",
            help: "Rate limits, daily message limits and monthly token budgets keep one client from using everything up." },
};

export const STATE_LABEL: Record<MonitorState, string> = { live: "Live", on: "On", off: "Off", warn: "Check" };

const REASONS: Record<string, string> = {
  revoked: "key revoked", expired: "key expired", profile_off: "access profile switched off", app_off: "its app is off",
  not_recognized: "key not recognized", paused: "app paused", setup: "setup not finished", inactive: "inactive",
  circuit_open: "failing repeatedly, calls paused", failing: "recent calls or health check failing", removed: "provider removed",
  turned_off: "provider turned off", no_key: "no API key",
};

export function stateText(state: MonitorState, reason: string | null): string {
  const label = state === "live" ? "Live: traffic in the last 5 minutes" : state === "on" ? "On: ready" : STATE_LABEL[state];
  return reason ? `${STATE_LABEL[state]} · ${REASONS[reason] ?? reason}` : label;
}

export const WINDOW_TEXT: Record<string, string> = { "5m": "last 5 minutes", "1h": "last hour", "24h": "last 24 hours" };

