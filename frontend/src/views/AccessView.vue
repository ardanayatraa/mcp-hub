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
const mailerReady = ref(false);
const busy = ref(false);
const oneTimeLink = ref("");
const oneTimeInviteId = ref("");

const userForm = ref({ open: false, role: "hub_admin", app_ids: [] as string[] });
const editingUser = ref<AdminUserRow | null>(null);

async function load() {
  try {
    const [nextApps, nextUsers, system] = await Promise.all([hub.apps(), session.isRoot ? hub.users() : Promise.resolve([]),
      session.isRoot ? hub.system() : Promise.resolve(null)]);
    apps.value = nextApps;
    users.value = nextUsers;
    mailerReady.value = system?.security.email_delivery_ready === true;
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

async function resendInvite(user: AdminUserRow) {
  busy.value = true;
  try {
    const result = await hub.resendInvite(user.id);
    oneTimeLink.value = result.activation_url;
    oneTimeInviteId.value = user.id;
    toast.ok("New activation link ready");
    await load();
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    busy.value = false;
  }
}

async function saveUser() {
  busy.value = true;
  const wasEditing = !!editingUser.value;
  try {
    if (editingUser.value) {
      const { id, role, is_active, app_ids } = editingUser.value;
      await hub.updateUser(id, { role, is_active, app_ids: role === "hub_admin" ? [] : app_ids });
      editingUser.value = null;
    } else {
      const form = userForm.value;
      const result = await hub.createUser({ role: form.role, app_ids: form.role === "hub_admin" ? [] : form.app_ids });
      oneTimeLink.value = result.activation_url;
      oneTimeInviteId.value = result.id;
      userForm.value = { open: false, role: "hub_admin", app_ids: [] };
    }
    toast.ok(wasEditing ? "Team updated" : "Activation link ready");
    await load();
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    busy.value = false;
  }
}

async function copyLink() {
  try {
    await navigator.clipboard.writeText(oneTimeLink.value);
    toast.ok("Activation link copied");
  } catch {
    toast.error("Copy failed. Select and copy the link below.");
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
    <div v-if="oneTimeLink" class="card card-pad mb-4 space-y-2">
      <p class="text-sm font-semibold">Activation link · Invite {{ oneTimeInviteId.slice(0, 8) }}</p>
      <p class="text-xs text-subtle">Share this link privately with the team member. It expires in 24 hours and cannot be shown again after you close it. They will enter their real email, verify a code, then set a password.</p>
      <input class="input w-full" :value="oneTimeLink" readonly aria-label="Activation link" @focus="($event.target as HTMLInputElement).select()" />
      <div class="flex gap-2"><button class="btn-primary btn-sm" type="button" @click="copyLink">Copy link</button><button class="btn-secondary btn-sm" type="button" @click="oneTimeLink = ''">Done</button></div>
    </div>
    <div class="mb-4 flex items-center justify-between gap-3">
      <p v-if="!mailerReady" class="text-xs text-subtle">Email delivery needs SMTP settings before you can invite a new admin.</p>
      <span v-else />
      <button class="btn-primary" type="button" :disabled="!mailerReady" @click="userForm.open = true"><AppIcon name="plus" :size="16" /> Add team member</button>
    </div>
    <LoadingSkeleton v-if="!usersLoaded" label="Loading team" />
    <div v-else class="card overflow-x-auto">
      <table class="tbl">
        <thead><tr><th>Email</th><th>Role</th><th>Apps</th><th>MFA</th><th>Status</th><th /></tr></thead>
        <tbody>
          <tr v-for="user in users" :key="user.id">
            <td class="font-medium">{{ user.email || `Invite ${user.id.slice(0, 8)} · awaiting email` }}<span v-if="user.id === session.user?.id" class="badge-brand ml-2">you</span></td>
            <td class="text-xs">{{ user.is_root ? "Root" : roles.find((role) => role[0] === user.role)?.[1] ?? user.role }}</td>
            <td class="text-xs text-subtle">{{ ["super_admin", "hub_admin"].includes(user.role) ? "All apps" : user.app_ids.map(appName).join(", ") || "None assigned" }}</td>
            <td><span :class="user.mfa_enabled ? 'badge-ok' : 'badge-neutral'">{{ user.pending_activation ? "Activation code" : user.auth_method === "password" ? "Password" : user.mfa_enabled ? "Authenticator" : "Off" }}</span></td>
            <td><span :class="user.is_active && !user.pending_activation ? 'badge-ok' : 'badge-neutral'">{{ !user.is_active ? "Disabled" : user.pending_activation ? "Pending" : "Active" }}</span></td>
            <td class="text-right whitespace-nowrap"><button v-if="user.pending_activation && user.is_active" class="btn-ghost btn-sm" type="button" :disabled="busy || !mailerReady" @click="resendInvite(user)">New link</button><button v-if="!user.is_root" class="btn-ghost btn-sm" type="button" @click="editingUser = { ...user, app_ids: [...user.app_ids] }">Edit</button></td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>

  <ModalDialog v-if="userForm.open || editingUser" :title="editingUser ? `Edit ${editingUser.email || `invite ${editingUser.id.slice(0, 8)}`}` : 'Add team member'" @close="userForm.open = false; editingUser = null">
    <form id="user-form" class="space-y-4" @submit.prevent="saveUser">
      <template v-if="!editingUser">
        <p class="text-sm text-subtle">Choose the member's role and app access. After saving, share the activation link privately. They will enter their email, verify its code, and set a password.</p>
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
      <div v-if="editingUser && editingUser.auth_method === 'totp' && editingUser.id !== session.user?.id" class="flex items-center justify-between gap-3 rounded-lg border border-line p-2.5">
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
