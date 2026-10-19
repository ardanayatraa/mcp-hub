<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

import ModalDialog from "@/components/ModalDialog.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import { hub, type AppSummary, type Skill, type SkillDraft, type Tool } from "@/services/hub";
import { useToast } from "@/stores/toast";
import { byReadiness, errorMessage, slugify } from "@/utils/format";

const props = defineProps<{ apps: AppSummary[]; skill?: Skill | null; connectorId?: string }>();
const emit = defineEmits<{ close: []; saved: [Skill] }>();
const toast = useToast();

const HUB_TOOLS = [
  { name: "list_data_sources", label: "List data sources" },
  { name: "run_report", label: "Run report" },
  { name: "recall_memory", label: "Recall memory (needs memory on)" },
  { name: "save_memory", label: "Save memory (needs memory on)" },
  { name: "forget_memory", label: "Forget memory (needs memory on)" },
];

const editing = computed(() => !!props.skill);
const eligible = computed(() => byReadiness(props.apps.filter((app) => app.status !== "archived")));
const connectorId = ref(props.skill?.connector_id ?? props.connectorId ?? eligible.value[0]?.id ?? "");
const form = ref<SkillDraft>(props.skill
  ? { key: props.skill.key, title: props.skill.title, description: props.skill.description, instructions: props.skill.instructions,
      arguments: props.skill.arguments.map((item) => ({ ...item })), tools: [...props.skill.tools], enabled: props.skill.enabled }
  : { key: "", title: "", description: "", instructions: "", arguments: [], tools: ["run_report"], enabled: true });
const keyEdited = ref(editing.value);
const templates = ref<SkillDraft[]>([]);
const appTools = ref<Tool[]>([]);
const sample = ref<Record<string, string>>({});
const previewText = ref("");
const busy = ref<"" | "save" | "preview">("");
const instructionsBox = ref<HTMLTextAreaElement | null>(null);

onMounted(async () => {
  try {
    [templates.value, appTools.value] = await Promise.all([hub.skillTemplates(), hub.tools()]);
  } catch (exc) {
    toast.error(errorMessage(exc));
  }
});

watch(() => form.value.title, (title) => { if (!keyEdited.value) form.value.key = slugify(title).replace(/^app_/, "skill_"); });

const app = computed(() => props.apps.find((item) => item.id === connectorId.value));
const toolChoices = computed(() => [
  ...HUB_TOOLS,
  ...appTools.value.filter((tool) => tool.app_id === app.value?.app_id && tool.status !== "archived")
    .map((tool) => ({ name: tool.mcp_name, label: `${tool.display_title}${tool.status === "published" ? "" : " (not live)"}` })),
]);
const placeholders = computed(() => [...form.value.instructions.matchAll(/\{\{\s*([a-z][a-z0-9_]*)\s*\}\}/g)].map((match) => match[1]));
const undeclared = computed(() => [...new Set(placeholders.value)].filter((name) => !form.value.arguments.some((item) => item.name === name)));
const valid = computed(() => connectorId.value && /^[a-z][a-z0-9_]{1,63}$/.test(form.value.key) && form.value.title.trim()
  && form.value.description.trim().length >= 3 && form.value.instructions.trim().length >= 10 && !undeclared.value.length);

function useTemplate(event: Event) {
  const chosen = templates.value.find((item) => item.key === (event.target as HTMLSelectElement).value);
  if (!chosen) return;
  form.value = { ...chosen, arguments: chosen.arguments.map((item) => ({ ...item })), tools: [...chosen.tools], enabled: true };
  keyEdited.value = true;
  previewText.value = "";
}

function addArgument() {
  form.value.arguments.push({ name: `value_${form.value.arguments.length + 1}`, description: "", required: false });
}

function token(name: string) {
  return `{{${name}}}`;
}

function insertPlaceholder(name: string) {
  const box = instructionsBox.value;
  const inserted = token(name);
  const text = form.value.instructions;
  const start = box?.selectionStart ?? text.length;
  const end = box?.selectionEnd ?? text.length;
  form.value.instructions = text.slice(0, start) + inserted + text.slice(end);
  requestAnimationFrame(() => { box?.focus(); box?.setSelectionRange(start + inserted.length, start + inserted.length); });
}

async function preview() {
  busy.value = "preview";
  try {
    previewText.value = (await hub.previewSkill({ connector_id: connectorId.value, skill: form.value, arguments: sample.value })).text;
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    busy.value = "";
  }
}

async function save() {
  busy.value = "save";
  try {
    const saved = props.skill ? await hub.updateSkill(props.skill.id, form.value)
      : await hub.createSkill({ ...form.value, connector_id: connectorId.value });
    toast.ok(`${saved.title} saved`);
    emit("saved", saved);
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    busy.value = "";
  }
}
</script>

<template>
  <ModalDialog :title="editing ? `Edit ${skill?.title}` : 'New skill'" wide @close="busy || emit('close')">
    <form id="skill-form" class="space-y-5" @submit.prevent="save">
      <div class="grid gap-4 sm:grid-cols-2">
        <label><span class="label">App</span>
          <select v-model="connectorId" class="input" :disabled="editing" required>
            <option v-for="item in eligible" :key="item.id" :value="item.id">{{ item.name }} · {{ item.environment }}</option>
          </select></label>
        <label v-if="!editing"><span class="label">Start from a template</span>
          <select class="input" @change="useTemplate">
            <option value="">Blank skill</option>
            <option v-for="item in templates" :key="item.key" :value="item.key">{{ item.title }}</option>
          </select></label>
        <label><span class="label">Title</span><input v-model="form.title" class="input" maxlength="120" required placeholder="Weekly sales report" /></label>
        <label><span class="label">Command name</span>
          <input v-model="form.key" class="input font-mono" maxlength="64" pattern="[a-z][a-z0-9_]{1,63}" required @input="keyEdited = true" />
          <span class="hint">AI clients show it like a slash command, for example /{{ form.key || "weekly_report" }}.</span></label>
        <label class="sm:col-span-2"><span class="label">Description</span>
          <input v-model="form.description" class="input" maxlength="300" required placeholder="What the skill does, in one sentence" /></label>
      </div>

      <div>
        <div class="mb-2 flex flex-wrap items-center justify-between gap-2">
          <label class="label mb-0" for="skill-instructions">Instructions for the AI</label>
          <span v-if="form.arguments.length" class="flex flex-wrap gap-1 text-xs text-subtle">Insert:
            <button v-for="item in form.arguments" :key="item.name" type="button" class="code hover:bg-line" @click="insertPlaceholder(item.name)">{{ token(item.name) }}</button>
          </span>
        </div>
        <textarea id="skill-instructions" ref="instructionsBox" v-model="form.instructions" class="input font-mono text-xs" rows="7" maxlength="4000" required
                  placeholder="Prepare a report on {{source}} for {{period}}. Use run_report and show the totals." />
        <p v-if="undeclared.length" class="mt-1.5 text-xs text-bad">Add an argument named {{ undeclared.join(", ") }} or remove the placeholder.</p>
        <p v-else class="hint">Write it as the user's request. Values in double braces come from the arguments below. No personal data.</p>
      </div>

      <div>
        <div class="mb-2 flex items-center justify-between">
          <span class="label mb-0">Arguments</span>
          <button type="button" class="btn-ghost btn-sm" :disabled="form.arguments.length >= 5" @click="addArgument"><AppIcon name="plus" :size="14" /> Add</button>
        </div>
        <p v-if="!form.arguments.length" class="text-xs text-subtle">None. The skill runs as written.</p>
        <div v-for="(item, index) in form.arguments" :key="index" class="mb-2 grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)_auto_auto] items-center gap-2">
          <input v-model="item.name" class="input font-mono text-xs" pattern="[a-z][a-z0-9_]{0,31}" required aria-label="Argument name" />
          <input v-model="item.description" class="input text-xs" maxlength="200" placeholder="What to enter" aria-label="Argument description" />
          <label class="flex items-center gap-1.5 text-xs"><input v-model="item.required" type="checkbox" /> Required</label>
          <button type="button" class="btn-ghost btn-sm btn-icon" aria-label="Remove argument" @click="form.arguments.splice(index, 1)"><AppIcon name="x" :size="14" /></button>
        </div>
      </div>

      <fieldset>
        <legend class="label">Tools the skill uses</legend>
        <p class="mb-2 text-xs text-subtle">A client key that cannot call every chosen tool does not see the skill.</p>
        <div class="grid max-h-44 gap-1.5 overflow-y-auto rounded-lg border border-line p-3 sm:grid-cols-2">
          <label v-for="tool in toolChoices" :key="tool.name" class="flex items-center gap-2 text-sm">
            <input v-model="form.tools" type="checkbox" :value="tool.name" /> <span class="truncate">{{ tool.label }}</span>
          </label>
        </div>
      </fieldset>

      <label class="flex items-center gap-3"><ToggleSwitch v-model="form.enabled" label="Enabled" /> <span class="text-sm">Offer this skill to AI clients</span></label>

      <div class="rounded-lg border border-line bg-muted/40 p-4">
        <div class="flex flex-wrap items-end gap-2">
          <label v-for="item in form.arguments" :key="item.name" class="min-w-[9rem] flex-1"><span class="label text-xs">{{ item.name }}</span>
            <input v-model="sample[item.name]" class="input text-xs" :placeholder="item.description || item.name" /></label>
          <button type="button" class="btn-secondary" :disabled="!valid || busy !== ''" @click="preview">
            <span v-if="busy === 'preview'" class="spinner" /><AppIcon v-else name="eye" :size="16" /> Preview</button>
        </div>
        <pre v-if="previewText" class="mt-3 whitespace-pre-wrap rounded-md bg-surface p-3 text-xs leading-relaxed">{{ previewText }}</pre>
        <p v-else class="mt-2 text-xs text-subtle">See exactly what the AI client receives when someone uses the skill.</p>
      </div>
    </form>
    <template #footer>
      <button class="btn-secondary" type="button" :disabled="busy !== ''" @click="emit('close')">Cancel</button>
      <button class="btn-primary" type="submit" form="skill-form" :disabled="!valid || busy !== ''">
        <span v-if="busy === 'save'" class="spinner" /> {{ editing ? "Save" : "Create skill" }}</button>
    </template>
  </ModalDialog>
</template>
