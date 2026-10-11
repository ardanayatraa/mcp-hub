<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import EmptyState from "@/components/EmptyState.vue";
import LoadingSkeleton from "@/components/LoadingSkeleton.vue";
import ModalDialog from "@/components/ModalDialog.vue";
import SkillEditor from "@/components/SkillEditor.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import { hub, type AppSummary, type Skill } from "@/services/hub";
import { useSession } from "@/stores/session";
import { useToast } from "@/stores/toast";
import { errorMessage, timeAgo } from "@/utils/format";

const props = defineProps<{ apps: AppSummary[] }>();
const emit = defineEmits<{ changed: [number] }>();
const session = useSession();
const toast = useToast();
const skills = ref<Skill[]>([]);
const loaded = ref(false);
const appFilter = ref("");
const editor = ref<{ open: boolean; skill: Skill | null }>({ open: false, skill: null });
const removing = ref<Skill | null>(null);
const busy = ref("");

async function load() {
  try {
    skills.value = await hub.skills();
    emit("changed", skills.value.length);
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    loaded.value = true;
  }
}
onMounted(load);

const visible = computed(() => skills.value.filter((skill) => !appFilter.value || skill.connector_id === appFilter.value));
const activeApps = computed(() => props.apps.filter((app) => app.status !== "archived"));

async function toggle(skill: Skill, enabled: boolean) {
  busy.value = skill.id;
  try {
    Object.assign(skill, await hub.updateSkill(skill.id, { enabled }));
    toast.ok(enabled ? `${skill.title} is offered to AI clients` : `${skill.title} is hidden from AI clients`);
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    busy.value = "";
  }
}

async function remove() {
  if (!removing.value) return;
  busy.value = removing.value.id;
  try {
    await hub.deleteSkill(removing.value.id);
    toast.ok("Skill deleted");
    removing.value = null;
    await load();
  } catch (exc) {
    toast.error(errorMessage(exc));
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
  <section>
    <div class="mb-4 flex flex-wrap items-center gap-2">
      <p class="mr-auto max-w-2xl text-sm text-subtle">
        Skills are reusable instructions AI clients show like slash commands, for example <span class="code">/weekly_report</span>.
        They are text only and use tools the client key may call anyway.
      </p>
      <select v-model="appFilter" class="input w-48" aria-label="Filter by app">
        <option value="">All apps</option>
        <option v-for="app in apps" :key="app.id" :value="app.id">{{ app.name }}</option>
      </select>
      <button v-if="session.canWrite" class="btn-primary" type="button" :disabled="!activeApps.length" @click="editor = { open: true, skill: null }">
        <AppIcon name="plus" :size="16" /> New skill</button>
    </div>

    <LoadingSkeleton v-if="!loaded" variant="cards" :count="3" label="Loading skills" />
    <EmptyState v-else-if="!visible.length" icon="sparkles" title="No skills yet"
                text="Start from a template such as Periodic report or Personal briefing, then adjust the wording for your team.">
      <button v-if="session.canWrite && activeApps.length" class="btn-primary" type="button" @click="editor = { open: true, skill: null }">Create a skill</button>
    </EmptyState>
    <div v-else class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      <article v-for="skill in visible" :key="skill.id" class="card flex flex-col">
        <div class="flex flex-1 flex-col gap-3 p-5">
          <div class="flex items-start justify-between gap-2">
            <div class="min-w-0">
              <p class="truncate font-semibold">{{ skill.title }}</p>
              <p class="truncate font-mono text-xs text-subtle">/{{ skill.key }} · {{ skill.app_name }}</p>
            </div>
            <ToggleSwitch :model-value="skill.enabled" :label="`Offer ${skill.title}`" :disabled="!session.canWrite || busy === skill.id"
                          @update:model-value="(on: boolean) => toggle(skill, on)" />
          </div>
          <p class="text-sm text-subtle">{{ skill.description }}</p>
          <div v-if="skill.arguments.length" class="flex flex-wrap gap-1">
            <span v-for="item in skill.arguments" :key="item.name" class="badge-outline font-mono">{{ item.name }}{{ item.required ? "" : "?" }}</span>
          </div>
          <div class="flex flex-wrap gap-1">
            <span v-for="tool in skill.tools" :key="tool" :class="skill.unavailable_tools.includes(tool) ? 'badge-warn' : 'badge-neutral'" class="font-mono">{{ tool }}</span>
          </div>
          <p v-if="skill.unavailable_tools.length" class="flex items-start gap-1.5 text-xs text-warn">
            <AppIcon name="alert" :size="14" class="mt-px" /> Hidden from AI clients until {{ skill.unavailable_tools.join(", ") }} {{ skill.unavailable_tools.length === 1 ? "is" : "are" }} live.
          </p>
        </div>
        <footer class="flex items-center gap-1 border-t border-line px-3 py-2">
          <span class="mr-auto pl-2 text-xs text-subtle">Updated {{ timeAgo(skill.updated_at) }}</span>
          <template v-if="session.canWrite">
            <button class="btn-ghost btn-sm" type="button" @click="editor = { open: true, skill }"><AppIcon name="pencil" :size="14" /> Edit</button>
            <button class="btn-ghost btn-sm text-bad hover:bg-bad-soft hover:text-bad" type="button" @click="removing = skill"><AppIcon name="trash" :size="14" /> Delete</button>
          </template>
        </footer>
      </article>
    </div>

    <SkillEditor v-if="editor.open" :apps="apps" :skill="editor.skill" :connector-id="appFilter || undefined"
                 @close="editor = { open: false, skill: null }" @saved="saved" />

    <ModalDialog v-if="removing" :title="`Delete ${removing.title}?`" @close="removing = null">
      <p class="text-sm text-subtle">AI clients stop offering /{{ removing.key }} immediately. Tools and data are not affected.</p>
      <template #footer>
        <button class="btn-secondary" type="button" @click="removing = null">Cancel</button>
        <button class="btn-danger" type="button" :disabled="busy !== ''" @click="remove"><span v-if="busy" class="spinner" /> Delete skill</button>
      </template>
    </ModalDialog>
  </section>
</template>
