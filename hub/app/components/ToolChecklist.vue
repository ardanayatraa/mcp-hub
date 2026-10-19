<script setup lang="ts">
import { computed } from "vue";

import type { DataSource, ToolSwitchRow } from "@/services/hub";
import { kindStyle, toolKind } from "@/utils/toolKinds";

// The connect wizard's "which tools may AI clients use?" list, grouped by data source.
// Create, update and delete stay unticked by default and cannot be ticked when the app's API is read-only.
const props = defineProps<{ rows: ToolSwitchRow[]; sources: DataSource[]; readOnly?: boolean }>();
const checked = defineModel<Record<string, boolean>>({ required: true });

const WRITES = ["create", "update", "delete"] as const;
const LABELS: Record<string, string> = { create: "Create", update: "Update", delete: "Delete" };

interface Item { key: string; row: ToolSwitchRow | null; title: string; name: string; kind: string; reason: string | null; write: boolean }

function kindOf(row: ToolSwitchRow) {
  if (row.kind === "hub") return row.template === "report" ? "report" : "hub";
  if (row.kind === "memory") return "memory";
  return toolKind(row.template, row.name.replaceAll("__", "."));
}

/** Why a row cannot be ticked here, or null when it can. */
function reason(row: ToolSwitchRow): string | null {
  if (props.readOnly) return "You can view this app but not change it";
  if (row.kind === "memory") return "Memory is off: turn it on in the app's Memory tab later";
  if (row.status === "disabled") return "Disabled on its page";
  return null;
}

const groups = computed(() => {
  const byName = new Map(props.sources.map((source) => [source.name, source]));
  const order = (name: string) => (name === "Hub tools" ? "0" : name === "Memory" ? "2" : `1${name}`);
  const names = [...new Set(props.rows.map((row) => row.group))].sort((a, b) => order(a).localeCompare(order(b), undefined, { numeric: true }));
  return names.map((name) => {
    const rows = props.rows.filter((row) => row.group === name);
    // "Changes data" means the app's records; memory tools only touch the user's own notes.
    const items: Item[] = rows.map((row) => ({ key: row.name, row, title: row.title, name: row.name, kind: kindOf(row),
                                              reason: reason(row), write: row.write && row.kind === "app" }));
    const source = byName.get(name);
    // Write operations the app's API does not offer still show, switched off, so the limit is visible.
    const missing = source ? WRITES.filter((op) => !source.enableable_operations.includes(op) && !rows.some((row) => row.template === op)) : [];
    for (const op of missing) {
      items.push({ key: `${name}:${op}`, row: null, title: `${LABELS[op]} ${(source?.name ?? "").toLowerCase()}`.trim(), name: "", kind: op,
                   reason: "The app's API is read-only here: it offers no route for this", write: true });
    }
    const open = items.filter((item) => item.row && !item.reason);
    return { name, source, items, open, readOnlyApi: source ? !WRITES.some((op) => source.enableable_operations.includes(op)) : false };
  });
});

const selectable = computed(() => groups.value.flatMap((group) => group.open));
const ticked = computed(() => selectable.value.filter((item) => checked.value[item.key]).length);

function toggle(name: string, on: boolean) {
  checked.value = { ...checked.value, [name]: on };
}

function groupState(open: Item[]) {
  const on = open.filter((item) => checked.value[item.key]).length;
  return { all: open.length > 0 && on === open.length, some: on > 0 && on < open.length };
}

function toggleGroup(open: Item[], on: boolean) {
  checked.value = { ...checked.value, ...Object.fromEntries(open.map((item) => [item.key, on])) };
}
</script>

<template>
  <div class="space-y-4">
    <p class="text-sm"><span class="font-medium tabular-nums">{{ ticked }}</span> of {{ selectable.length }} tools allowed.
      <span class="text-subtle">Unticked tools stay off; you can switch them on later on the app's Tools tab.</span></p>
    <fieldset v-for="group in groups" :key="group.name" class="rounded-lg border border-line">
      <legend class="sr-only">{{ group.name }}</legend>
      <div class="flex flex-wrap items-center justify-between gap-2 border-b border-line bg-muted/40 px-4 py-2.5">
        <label class="flex items-center gap-2 text-sm font-medium" :class="group.open.length ? 'cursor-pointer' : ''">
          <input type="checkbox" :checked="groupState(group.open).all" :indeterminate="groupState(group.open).some"
                 :disabled="!group.open.length" :aria-label="`All tools of ${group.name}`"
                 @change="toggleGroup(group.open, ($event.target as HTMLInputElement).checked)" />
          {{ group.name }}
        </label>
        <span v-if="group.readOnlyApi" class="badge-neutral"><AppIcon name="lock" :size="12" /> API is read-only</span>
      </div>
      <ul class="divide-y divide-line">
        <li v-for="item in group.items" :key="item.key">
          <label class="flex items-start gap-3 px-4 py-2.5" :class="item.reason ? 'opacity-60' : 'cursor-pointer hover:bg-muted/30'">
            <input type="checkbox" class="mt-1.5" :checked="!item.reason && !!checked[item.key]" :disabled="!!item.reason"
                   :aria-describedby="item.reason ? `why-${item.key}` : undefined"
                   @change="toggle(item.key, ($event.target as HTMLInputElement).checked)" />
            <span class="grid h-7 w-7 shrink-0 place-items-center rounded-md" :class="kindStyle(item.kind).tile">
              <AppIcon :name="kindStyle(item.kind).icon" :size="14" /></span>
            <span class="min-w-0 flex-1">
              <span class="flex flex-wrap items-center gap-x-2">
                <span class="text-sm font-medium">{{ item.title }}</span>
                <span v-if="item.write" class="badge-warn">Changes data</span>
              </span>
              <span v-if="item.name" class="block truncate font-mono text-xs text-subtle">{{ item.name }}</span>
              <span v-if="item.reason" :id="`why-${item.key}`" class="block text-xs text-subtle">{{ item.reason }}</span>
              <span v-else-if="item.write && checked[item.key]" class="block text-xs text-subtle">
                Tested with sample data and published when you finish. Each change still waits for the user's confirmation in the app.</span>
            </span>
          </label>
        </li>
      </ul>
    </fieldset>
  </div>
</template>
