import { ApiError } from "@/services/api";

export function errorMessage(exc: unknown, fallback = "Something went wrong"): string {
  if (exc instanceof ApiError) return exc.message;
  if (exc instanceof Error) return exc.message;
  return fallback;
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "never";
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days} d ago`;
  return new Date(iso).toLocaleDateString();
}

export function dateTime(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : "—";
}

export function untilLabel(iso: string | null | undefined): string {
  if (!iso) return "no expiry";
  const days = Math.round((new Date(iso).getTime() - Date.now()) / 86_400_000);
  if (days < 0) return "expired";
  if (days === 0) return "expires today";
  return `expires in ${days} d`;
}

type Tone = "ok" | "warn" | "bad" | "brand" | "neutral";

export function badgeClass(tone: Tone): string {
  return `badge-${tone}`;
}

export const appStatus: Record<string, { label: string; tone: Tone }> = {
  draft: { label: "Setup", tone: "warn" },
  active: { label: "Active", tone: "ok" },
  paused: { label: "Paused", tone: "neutral" },
  archived: { label: "Archived", tone: "neutral" },
};

export function toolStatus(tool: { status: string; stale: boolean }): { label: string; tone: Tone } {
  if (tool.status === "published" && tool.stale) return { label: "Needs re-test", tone: "warn" };
  return (
    { published: { label: "Live", tone: "ok" as Tone }, draft: { label: "Draft", tone: "neutral" as Tone },
      disabled: { label: "Disabled", tone: "neutral" as Tone }, archived: { label: "Archived", tone: "neutral" as Tone } }[tool.status]
    ?? { label: tool.status, tone: "neutral" }
  );
}

export const templateInfo: Record<string, { label: string; icon: string; tone: Tone }> = {
  read: { label: "Read records", icon: "table", tone: "brand" },
  report: { label: "Report", icon: "chart", tone: "brand" },
  create: { label: "Create", icon: "plus", tone: "warn" },
  update: { label: "Update", icon: "pencil", tone: "warn" },
  delete: { label: "Delete", icon: "trash", tone: "bad" },
};

export const classification: Record<string, { label: string; tone: Tone; help: string }> = {
  allowed_for_ai: { label: "Visible to AI", tone: "ok", help: "Can be returned, filtered and grouped." },
  allowed: { label: "Visible to AI", tone: "ok", help: "Can be returned, filtered and grouped." },
  aggregate_only: { label: "Totals only", tone: "warn", help: "Only sums and averages over 3+ records." },
  blocked: { label: "Hidden", tone: "neutral", help: "Never leaves the Hub." },
  secure_form_only: { label: "Hidden (secure form)", tone: "neutral", help: "Entered only in the app's own forms." },
};

const ACTIONS: Record<string, string> = {
  "tool.execute": "Tool call",
  "tool.create": "Tool created",
  "tool.update": "Tool edited",
  "tool.test": "Tool tested",
  "tool.publish": "Tool published",
  "tool.disable": "Tool disabled",
  "tool.delete": "Tool deleted",
  "tool.approve": "Tool approved",
  "connector.create": "App added",
  "connector.update": "App settings changed",
  "connector.test": "Connection tested",
  "connector.discover": "Contract synced",
  "connector.activate": "App activated",
  "connector.pause": "App paused",
  "connector.rotate": "Credential rotated",
  "connector.archive": "App archived",
  "connector.delete": "App deleted",
  "secret.rotate": "Credential rotated",
  "secret.revoke": "Credential revoked",
  "module.update": "Data source changed",
  "key.create": "Client key created",
  "key.update": "Client key changed",
  "key.revoke": "Client key revoked",
  "identity.create": "Client key created",
  "identity.revoke": "Client key revoked",
  "admin.create": "Admin added",
  "admin.update": "Admin changed",
  "admin.scope_update": "Admin access changed",
  "auth.login": "Sign-in",
  "auth.logout": "Sign-out",
  "auth.mfa": "MFA check",
  "auth.mfa_challenge": "MFA challenge",
  "backup.export": "Backup exported",
  "backup.import": "Backup restored",
  "backup.purge": "Old records purged",
  "tool.generate": "Tools generated",
  "skill.create": "Skill created",
  "skill.update": "Skill changed",
  "skill.delete": "Skill deleted",
  "skill.use": "Skill used",
  "memory.settings": "Memory settings changed",
  "memory.purge": "Memories deleted",
  "tool.switch_on": "Tool switched on",
  "tool.switch_off": "Tool switched off",
  "chat.turn": "Chat answer",
  "model.chat": "Model call (gateway)",
  "chat.settings": "Chat settings changed",
  "provider.create": "AI provider added",
  "provider.update": "AI provider changed",
  "provider.delete": "AI provider removed",
  "provider.test": "AI provider tested",
  "connector.source_sync": "Permissions refreshed",
};

export function actionLabel(action: string): string {
  return ACTIONS[action] ?? action;
}

export function resultTone(result: string): Tone {
  return result === "success" ? "ok" : result === "denied" ? "warn" : "bad";
}

/** Active apps first, so pickers default to one that can actually serve AI clients. */
export function byReadiness<T extends { status: string; name: string }>(apps: T[]): T[] {
  const rank: Record<string, number> = { active: 0, paused: 1, draft: 2, archived: 3 };
  return [...apps].sort((a, b) => (rank[a.status] ?? 9) - (rank[b.status] ?? 9) || a.name.localeCompare(b.name));
}

export function slugify(text: string): string {
  return text.toLowerCase().trim().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").replace(/^(\d)/, "app_$1").slice(0, 40);
}

export function prettyJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}
