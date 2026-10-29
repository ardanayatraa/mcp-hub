<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import ClientKeysPanel from "@/components/ClientKeysPanel.vue";
import AccessProfilesPanel from "@/components/AccessProfilesPanel.vue";
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
const tab = ref(route.query.tab === "team" && session.isHubAdmin ? "team" : "keys");
const apps = ref<AppSummary[]>([]);
const profilesRevision = ref(0);
const appsLoaded = ref(false);
const appsError = ref("");
const users = ref<AdminUserRow[]>([]);
const usersLoaded = ref(false);
const mailerReady = ref(false);
const busy = ref(false);
const oneTimeLink = ref("");
const oneTimeInviteId = ref("");
const oneTimeExpiry = ref<string | null>(null);

const userForm = ref({ open: false, role: "hub_admin", app_ids: [] as string[], invite_expiry: "1_day" });
const editingUser = ref<AdminUserRow | null>(null);
const renewingUser = ref<AdminUserRow | null>(null);
const renewalExpiry = ref("1_day");

async function load() {
  const [appResult, userResult, systemResult] = await Promise.allSettled([
    hub.apps(), session.isHubAdmin ? hub.users() : Promise.resolve([]),
    session.isHubAdmin ? hub.system() : Promise.resolve(null),
  ]);
  if (appResult.status === "fulfilled") {
    apps.value = appResult.value;
    appsError.value = "";
  } else {
    appsError.value = errorMessage(appResult.reason);
  }
  if (userResult.status === "fulfilled") users.value = userResult.value;
  else toast.error(errorMessage(userResult.reason));
  if (systemResult.status === "fulfilled") mailerReady.value = systemResult.value?.security.email_delivery_ready === true;
  else toast.error(errorMessage(systemResult.reason));
  appsLoaded.value = true;
  usersLoaded.value = true;
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

async function resendInvite() {
  const user = renewingUser.value;
  if (!user) return;
  busy.value = true;
  try {
    const result = await hub.resendInvite(user.id, renewalExpiry.value);
    oneTimeLink.value = result.activation_url;
    oneTimeInviteId.value = user.id;
    oneTimeExpiry.value = result.activation_expires_at;
    renewingUser.value = null;
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
      const result = await hub.createUser({ role: form.role, app_ids: form.role === "hub_admin" ? [] : form.app_ids,
        invite_expiry: form.invite_expiry });
      oneTimeLink.value = result.activation_url;
      oneTimeInviteId.value = result.id;
      oneTimeExpiry.value = result.activation_expires_at;
      userForm.value = { open: false, role: "hub_admin", app_ids: [], invite_expiry: "1_day" };
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
  ["hub_admin", "Hub admin", "All apps and settings. Can add members; only root can change existing access."],
  ["app_admin", "App admin", "Manage assigned apps, tools and keys"],
  ["auditor", "Auditor", "Read-only access to assigned apps"],
] as const;
const appName = (appId: string) => apps.value.find((app) => app.app_id === appId)?.name ?? appId;
const expiryLabel = (iso: string | null) => iso ? `Expires ${new Date(iso).toLocaleString()}` : "Never expires";
</script>

<template>
  <PageHeader title="Access" subtitle="Client keys let AI clients call tools for one app. Team members manage the Hub." />
  <TabBar v-if="session.isHubAdmin" v-model="tab" :tabs="[{ key: 'keys', label: 'Client keys' }, { key: 'team', label: 'Team' }]" />

  <div v-if="tab === 'keys'" class="space-y-8">
    <ClientKeysPanel :key="profilesRevision" :apps="apps" :apps-loaded="appsLoaded" :apps-error="appsError" />
    <AccessProfilesPanel v-if="appsLoaded && !appsError" :apps="apps" @changed="profilesRevision++" />
  </div>

  <section v-else>
    <div v-if="oneTimeLink" class="card card-pad mb-4 space-y-2">
      <p class="text-sm font-semibold">Activation link · Invite {{ oneTimeInviteId.slice(0, 8) }}</p>
      <p class="text-xs text-subtle">Share this link privately with the team member. {{ expiryLabel(oneTimeExpiry) }}. It is shown once and is used once. They verify their email, set a password, then sign in with email and password.</p>
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
            <td><span :class="user.is_active && !user.pending_activation ? 'badge-ok' : 'badge-neutral'">{{ !user.is_active ? "Disabled" : user.pending_activation ? "Pending" : "Active" }}</span><p v-if="user.pending_activation && user.is_active" class="mt-1 text-xs text-subtle">{{ expiryLabel(user.activation_expires_at) }}</p></td>
            <td class="text-right whitespace-nowrap"><button v-if="session.isRoot && user.pending_activation && user.is_active" class="btn-ghost btn-sm" type="button" :disabled="busy || !mailerReady" @click="renewingUser = user">New link</button><button v-if="session.isRoot && !user.is_root" class="btn-ghost btn-sm" type="button" @click="editingUser = { ...user, app_ids: [...user.app_ids] }">Edit</button></td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>

  <ModalDialog v-if="userForm.open || editingUser" :title="editingUser ? `Edit ${editingUser.email || `invite ${editingUser.id.slice(0, 8)}`}` : 'Add team member'" @close="userForm.open = false; editingUser = null">
    <form id="user-form" class="space-y-4" @submit.prevent="saveUser">
      <template v-if="!editingUser">
        <p class="text-sm text-subtle">Choose the member's role and app access. After saving, share the activation link privately. They will verify their email once and set a password for future sign-ins.</p>
        <label class="block"><span class="label">Activation link expires after</span>
          <select v-model="userForm.invite_expiry" class="input"><option value="1_day">1 day</option><option value="1_week">1 week</option><option value="1_month">1 month</option><option value="never">Never</option></select>
        </label>
        <p v-if="userForm.invite_expiry === 'never'" class="text-xs text-subtle">The link stays valid until it is used, the account is disabled, or root replaces it.</p>
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

  <ModalDialog v-if="renewingUser" title="Create a new activation link" @close="renewingUser = null">
    <p class="mb-3 text-sm text-subtle">The current link will stop working when you create a new one.</p>
    <label class="block"><span class="label">New link expires after</span>
      <select v-model="renewalExpiry" class="input"><option value="1_day">1 day</option><option value="1_week">1 week</option><option value="1_month">1 month</option><option value="never">Never</option></select>
    </label>
    <template #footer>
      <button class="btn-secondary" type="button" @click="renewingUser = null">Cancel</button>
      <button class="btn-primary" type="button" :disabled="busy" @click="resendInvite">Create link</button>
    </template>
  </ModalDialog>
</template>
