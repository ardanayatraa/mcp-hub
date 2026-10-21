<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import ClientKeysPanel from "@/components/ClientKeysPanel.vue";
import LoadingSkeleton from "@/components/LoadingSkeleton.vue";
import ModalDialog from "@/components/ModalDialog.vue";
import PageHeader from "@/components/PageHeader.vue";
import TabBar from "@/components/TabBar.vue";
import { hub, type AdminUserRow, type AppSummary } from "@/services/hub";
import { useSession } from "@/stores/session";
import { useToast } from "@/stores/toast";
import { errorMessage } from "@/utils/format";

const route = useRoute();
const session = useSession();
const toast = useToast();
const tab = ref(route.query.tab === "team" && session.isRoot ? "team" : "keys");
const apps = ref<AppSummary[]>([]);
const users = ref<AdminUserRow[]>([]);
const usersLoaded = ref(false);
const busy = ref(false);

const userForm = ref({ open: false, email: "", role: "app_admin", password: "", app_ids: [] as string[] });
const editingUser = ref<AdminUserRow | null>(null);

async function load() {
  try {
    const [nextApps, nextUsers] = await Promise.all([hub.apps(), session.isRoot ? hub.users() : Promise.resolve([])]);
    apps.value = nextApps;
    users.value = nextUsers;
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    usersLoaded.value = true;
  }
}
onMounted(load);

async function resetMfa(user: AdminUserRow) {
  if (!window.confirm(`Reset two-factor sign-in for ${user.email}? They are signed out and set it up again at their next sign-in.`)) return;
  busy.value = true;
  try {
    await hub.updateUser(user.id, { reset_mfa: true });
    editingUser.value = null;
    toast.ok("Two-factor sign-in reset");
    await load();
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    busy.value = false;
  }
}

async function saveUser() {
  busy.value = true;
  try {
    if (editingUser.value) {
      const { id, role, is_active, app_ids } = editingUser.value;
      await hub.updateUser(id, { role, is_active, app_ids: role === "hub_admin" ? [] : app_ids });
      editingUser.value = null;
    } else {
      const form = userForm.value;
      await hub.createUser({ email: form.email, role: form.role, password: form.password, app_ids: form.role === "hub_admin" ? [] : form.app_ids });
      userForm.value = { open: false, email: "", role: "app_admin", password: "", app_ids: [] };
    }
    toast.ok("Team updated");
    await load();
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    busy.value = false;
  }
}

const roles = [
  ["hub_admin", "Hub admin", "All apps and settings. Only root can manage team access."],
  ["app_admin", "App admin", "Manage assigned apps, tools and keys"],
  ["auditor", "Auditor", "Read-only access to assigned apps"],
] as const;
const appName = (appId: string) => apps.value.find((app) => app.app_id === appId)?.name ?? appId;
</script>

<template>
  <PageHeader title="Access" subtitle="Client keys let AI clients call tools for one app. Team members manage the Hub." />
  <TabBar v-if="session.isRoot" v-model="tab" :tabs="[{ key: 'keys', label: 'Client keys' }, { key: 'team', label: 'Team' }]" />

  <ClientKeysPanel v-if="tab === 'keys'" :apps="apps" />

  <section v-else>
    <div class="mb-4 flex justify-end">
      <button class="btn-primary" type="button" @click="userForm.open = true"><AppIcon name="plus" :size="16" /> Add team member</button>
    </div>
    <LoadingSkeleton v-if="!usersLoaded" label="Loading team" />
    <div v-else class="card overflow-x-auto">
      <table class="tbl">
        <thead><tr><th>Email</th><th>Role</th><th>Apps</th><th>MFA</th><th>Status</th><th /></tr></thead>
        <tbody>
          <tr v-for="user in users" :key="user.id">
            <td class="font-medium">{{ user.email }}<span v-if="user.id === session.user?.id" class="badge-brand ml-2">you</span></td>
            <td class="text-xs">{{ user.is_root ? "Root" : roles.find((role) => role[0] === user.role)?.[1] ?? user.role }}</td>
            <td class="text-xs text-subtle">{{ ["super_admin", "hub_admin"].includes(user.role) ? "All apps" : user.app_ids.map(appName).join(", ") || "None assigned" }}</td>
            <td><span :class="user.mfa_enabled ? 'badge-ok' : 'badge-neutral'">{{ user.mfa_enabled ? "On" : "Off" }}</span></td>
            <td><span :class="user.is_active ? 'badge-ok' : 'badge-neutral'">{{ user.is_active ? "Active" : "Disabled" }}</span></td>
            <td class="text-right"><button v-if="!user.is_root" class="btn-ghost btn-sm" type="button" @click="editingUser = { ...user, app_ids: [...user.app_ids] }">Edit</button></td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>

  <ModalDialog v-if="userForm.open || editingUser" :title="editingUser ? `Edit ${editingUser.email}` : 'Add team member'" @close="userForm.open = false; editingUser = null">
    <form id="user-form" class="space-y-4" @submit.prevent="saveUser">
      <template v-if="!editingUser">
        <label class="block"><span class="label">Email</span><input v-model="userForm.email" class="input" type="email" required /></label>
        <label class="block"><span class="label">Temporary password</span>
          <input v-model="userForm.password" class="input" type="password" autocomplete="new-password" minlength="12" required />
          <span class="hint">12+ characters with upper and lower case letters and a digit.</span></label>
      </template>
      <fieldset class="space-y-2">
        <legend class="label">Role</legend>
        <label v-for="[value, label, help] in roles" :key="value" class="flex items-start gap-3 rounded-lg border border-line p-2.5">
          <input v-if="editingUser" v-model="editingUser.role" type="radio" :value="value" class="mt-0.5" />
          <input v-else v-model="userForm.role" type="radio" :value="value" class="mt-0.5" />
          <span><span class="text-sm font-medium">{{ label }}</span><span class="block text-xs text-subtle">{{ help }}</span></span>
        </label>
      </fieldset>
      <fieldset v-if="(editingUser ? editingUser.role : userForm.role) !== 'hub_admin'" class="space-y-1.5">
        <legend class="label">Apps</legend>
        <label v-for="app in apps" :key="app.app_id" class="flex items-center gap-2 text-sm">
          <input v-if="editingUser" v-model="editingUser.app_ids" type="checkbox" :value="app.app_id" />
          <input v-else v-model="userForm.app_ids" type="checkbox" :value="app.app_id" />
          {{ app.name }} <span class="text-xs text-subtle">{{ app.environment }}</span>
        </label>
      </fieldset>
      <label v-if="editingUser" class="flex items-center gap-2 text-sm"><input v-model="editingUser.is_active" type="checkbox" /> Account active</label>
      <div v-if="editingUser && editingUser.id !== session.user?.id" class="flex items-center justify-between gap-3 rounded-lg border border-line p-2.5">
        <span class="text-sm">Two-factor sign-in<span class="block text-xs text-subtle">{{ editingUser.mfa_enabled
          ? "Set up. Reset it when they lose their authenticator."
          : "Not set up yet. Resetting gives them a new window to set it up." }}</span></span>
        <button class="btn-secondary btn-sm" type="button" :disabled="busy" @click="resetMfa(editingUser)">Reset</button>
      </div>
    </form>
    <template #footer>
      <button class="btn-secondary" type="button" @click="userForm.open = false; editingUser = null">Cancel</button>
      <button class="btn-primary" type="submit" form="user-form" :disabled="busy">Save</button>
    </template>
  </ModalDialog>
</template>
