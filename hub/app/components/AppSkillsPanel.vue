<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import LoadingSkeleton from "@/components/LoadingSkeleton.vue";
import SkillEditor from "@/components/SkillEditor.vue";
import { hub, type AppSummary, type Skill, type SkillDraft, type ToolSwitchRow } from "@/services/hub";
import { useToast } from "@/stores/toast";
import { errorMessage } from "@/utils/format";

// One app's skills as a checklist: ready-made skills (ticked when the app uses them) and its own.
const props = defineProps<{ app: AppSummary; editable: boolean }>();
const emit = defineEmits<{ changed: [number] }>();
const toast = useToast();

const skills = ref<Skill[]>([]);
const templates = ref<SkillDraft[]>([]);
const tools = ref<ToolSwitchRow[]>([]);
const loaded = ref(false);
const error = ref("");
const busy = ref("");
const editor = ref<{ open: boolean; skill: Skill | null }>({ open: false, skill: null });

interface Row { key: string; title: string; description: string; tools: string[]; skill: Skill | null; template: SkillDraft | null }

async function load() {
  try {
    const [own, ready, switches] = await Promise.all([hub.skills(props.app.id), hub.skillTemplates(), hub.toolSwitches(props.app.id)]);
    skills.value = own;
    templates.value = ready;
    tools.value = switches.tools;
    error.value = "";
  } catch (exc) {
    error.value = errorMessage(exc);
  } finally {
    loaded.value = true;
    emit("changed", skills.value.filter((skill) => skill.enabled).length);
  }
}
onMounted(load);

const byName = computed(() => new Map(tools.value.map((row) => [row.name, row])));
const readyRows = computed<Row[]>(() => templates.value.map((template) => {
  const skill = skills.value.find((item) => item.key === template.key) ?? null;
  return { key: template.key, title: skill?.title ?? template.title, description: skill?.description ?? template.description,
           tools: skill?.tools ?? template.tools, skill, template };
}));
const ownRows = computed<Row[]>(() => skills.value.filter((skill) => !templates.value.some((template) => template.key === skill.key))
  .map((skill) => ({ key: skill.key, title: skill.title, description: skill.description, tools: skill.tools, skill, template: null })));
const total = computed(() => readyRows.value.length + ownRows.value.length);
const on = computed(() => skills.value.filter((skill) => skill.enabled).length);

/** Tools the skill names that this app's AI cannot call right now. */
function missing(row: Row): string[] {
  if (row.skill) return row.skill.unavailable_tools;
  return row.tools.filter((name) => { const tool = byName.value.get(name); return !tool || !tool.live || !tool.enabled; });
}

/** Why the box cannot be ticked, or null. Unticking is always allowed. */
function blocked(row: Row): string | null {
  if (!props.editable) return "View only";
  if (row.skill?.enabled) return null;
  const names = missing(row);
  if (!names.length) return null;
  if (names.some((name) => byName.value.get(name)?.kind === "memory")) return "Needs memory: turn it on in the Memory tab first";
  if (names.some((name) => byName.value.get(name)?.write)) return "Needs tools that change data, which this app does not offer or has switched off";
  return `Needs tools that are off or not published: ${names.join(", ")}`;
}

function toolLabel(name: string) {
  return byName.value.get(name)?.title ?? name;
}

async function toggle(row: Row, enabled: boolean) {
  busy.value = row.key;
  try {
    if (row.skill) {
      Object.assign(row.skill, await hub.updateSkill(row.skill.id, { enabled }));
    } else if (enabled && row.template) {
      skills.value.push(await hub.createSkill({ ...row.template, enabled: true, connector_id: props.app.id }));
    }
    toast.ok(enabled ? `${row.title} is offered to AI clients` : `${row.title} is hidden from AI clients`);
    emit("changed", on.value);
  } catch (exc) {
    toast.error(errorMessage(exc));
    await load();
  } finally {
    busy.value = "";
  }
}

function saved() {
  editor.value = { open: false, skill: null };
  void load();
}
</script>

<template>
  <section class="space-y-6">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div class="max-w-2xl">
        <p class="text-sm"><span class="font-medium tabular-nums">{{ on }}</span> of {{ total }} skills on for {{ app.name }}.</p>
        <p class="text-xs text-subtle">Ticked skills appear in AI clients like slash commands, for example <span class="code">/periodic_report</span>,
          and in the Hub chat. A skill only shows when the client key may call every tool it names.</p>
      </div>
      <button v-if="editable" type="button" class="btn-secondary" @click="editor = { open: true, skill: null }">
        <AppIcon name="plus" :size="16" /> New skill</button>
    </div>

    <p v-if="error" role="alert" class="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{{ error }}</p>
    <LoadingSkeleton v-if="!loaded" label="Loading skills" variant="rows" :count="4" />

    <template v-else>
      <fieldset v-for="group in [{ name: 'Ready-made skills', rows: readyRows }, { name: `${app.name}'s own skills`, rows: ownRows }]"
                :key="group.name" class="rounded-lg border border-line">
        <legend class="sr-only">{{ group.name }}</legend>
        <p class="border-b border-line bg-muted/40 px-4 py-2.5 text-sm font-medium">{{ group.name }}
          <span class="ml-1 text-xs font-normal text-subtle">{{ group.rows.filter((row) => row.skill?.enabled).length }} of {{ group.rows.length }} on</span></p>
        <ul class="divide-y divide-line">
          <li v-for="row in group.rows" :key="row.key" class="flex items-start gap-3 px-4 py-3">
            <input type="checkbox" class="mt-1" :checked="!!row.skill?.enabled" :disabled="!!blocked(row) || busy === row.key"
                   :aria-label="`Offer ${row.title}`" :aria-describedby="blocked(row) ? `why-${row.key}` : undefined"
                   @change="toggle(row, ($event.target as HTMLInputElement).checked)" />
            <div class="min-w-0 flex-1" :class="blocked(row) && !row.skill?.enabled ? 'opacity-70' : ''">
              <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span class="font-medium">{{ row.title }}</span>
                <code class="font-mono text-xs text-subtle">/{{ row.key }}</code>
                <span v-if="!row.skill" class="badge-outline">Not added</span>
                <span v-else-if="row.skill.enabled && row.skill.unavailable_tools.length" class="badge-warn">Hidden: a tool is off</span>
                <span v-if="busy === row.key" class="spinner h-3.5 w-3.5" />
              </div>
              <p class="mt-0.5 text-sm text-subtle">{{ row.description }}</p>
              <div v-if="row.tools.length" class="mt-1.5 flex flex-wrap gap-1.5">
                <span v-for="name in row.tools" :key="name" class="badge-neutral" :class="missing(row).includes(name) ? 'line-through opacity-60' : ''"
                      :title="missing(row).includes(name) ? 'Not available to AI clients of this app right now' : 'Available'">
                  <AppIcon :name="missing(row).includes(name) ? 'x' : 'check'" :size="11" /> {{ toolLabel(name) }}
                  <span v-if="byName.get(name)?.write && byName.get(name)?.kind === 'app'" class="text-warn">· changes data</span>
                </span>
              </div>
              <p v-if="blocked(row) && blocked(row) !== 'View only'" :id="`why-${row.key}`" class="mt-1 flex items-center gap-1 text-xs text-subtle">
                <AppIcon name="lock" :size="12" /> {{ blocked(row) }}</p>
            </div>
            <button v-if="editable && row.skill" type="button" class="btn-ghost btn-sm" @click="editor = { open: true, skill: row.skill }">
              <AppIcon name="pencil" :size="14" /> Edit</button>
          </li>
          <li v-if="!group.rows.length" class="px-4 py-6 text-center text-sm text-subtle">
            No own skills yet. <button v-if="editable" type="button" class="link" @click="editor = { open: true, skill: null }">Write one</button></li>
        </ul>
      </fieldset>
    </template>

    <SkillEditor v-if="editor.open" :apps="[app]" :skill="editor.skill" :connector-id="app.id"
                 @close="editor = { open: false, skill: null }" @saved="saved" />
  </section>
</template>
