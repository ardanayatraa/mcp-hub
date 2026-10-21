<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import ThemeSwitch from "@/components/ThemeSwitch.vue";
import ToastHost from "@/components/ToastHost.vue";
import { useSession } from "@/stores/session";

const session = useSession();
const route = useRoute();
const router = useRouter();
const open = ref(false);
const collapsed = ref(readCollapsed());
const menuOpen = ref(false);
const menu = ref<HTMLElement | null>(null);
const content = ref<HTMLElement | null>(null);

const groups = computed(() => [
  {
    label: "Platform",
    links: [
      { label: "Overview", to: "/", icon: "home" },
      { label: "Apps", to: "/apps", icon: "apps" },
      { label: "Tools", to: "/tools", icon: "tools" },
      { label: "Access", to: "/access", icon: "key" },
      { label: "AI providers", to: "/providers", icon: "sparkles" },
      { label: "Activity", to: "/activity", icon: "activity" },
      ...(session.isHubAdmin ? [{ label: "Settings", to: "/settings", icon: "settings" }] : []),
    ],
  },
  { label: "Docs", links: [{ label: "Assistant", to: "/assistant", icon: "chat" }, { label: "User guide", to: "/docs/guide", icon: "book" },
    { label: "Laravel guide", to: "/docs/laravel", icon: "code" }] },
]);
const showShell = computed(() => !route.meta.public);
const roleLabel = computed(() => ({ super_admin: "Root", hub_admin: "Hub admin", app_admin: "App admin", auditor: "Auditor" })[session.user?.role ?? ""] ?? "");
const initials = computed(() => (session.user?.email ?? "?").split("@")[0].split(/[._-]/).filter(Boolean).slice(0, 2)
  .map((part) => part[0]?.toUpperCase()).join("") || "?");
const section = computed(() => groups.value.flatMap((group) => group.links).find((link) => active(link.to)));
const nested = computed(() => section.value && route.path !== section.value.to);
const leaf = computed(() => route.path.endsWith("/new") ? "New" : route.path === "/tools/report" ? "Report playground" : "Details");

function active(to: string) {
  return to === "/" ? route.path === "/" : route.path.startsWith(to);
}

// The collapsed rail is a per-browser preference; storage may be unavailable (private mode).
function readCollapsed(): boolean {
  try { return localStorage.getItem("hub_sidebar") === "collapsed"; } catch { return false; }
}

function toggleSidebar() {
  if (window.matchMedia("(min-width: 1024px)").matches) {
    collapsed.value = !collapsed.value;
    try { localStorage.setItem("hub_sidebar", collapsed.value ? "collapsed" : "expanded"); } catch { /* not persisted */ }
  } else {
    open.value = !open.value;
  }
}

function closeMenu(event: Event) {
  if (event instanceof KeyboardEvent ? event.key === "Escape" : !menu.value?.contains(event.target as Node)) menuOpen.value = false;
}
onMounted(() => {
  document.addEventListener("pointerdown", closeMenu);
  document.addEventListener("keydown", closeMenu);
});
onBeforeUnmount(() => {
  document.removeEventListener("pointerdown", closeMenu);
  document.removeEventListener("keydown", closeMenu);
});

watch(() => route.path, () => {
  open.value = false;
  menuOpen.value = false;
  content.value?.scrollTo({ top: 0, left: 0 });
}, { flush: "post" });

async function signOut() {
  menuOpen.value = false;
  await session.logout();
  await router.push("/login");
}
</script>

<template>
  <div v-if="showShell" class="flex h-dvh overflow-hidden bg-canvas print:block print:h-auto print:overflow-visible">
    <aside class="fixed inset-y-0 left-0 z-30 flex w-64 flex-col border-r border-line bg-sidebar transition-[width,transform] duration-200 lg:static lg:translate-x-0 print:hidden"
           :class="[open ? 'translate-x-0 shadow-pop' : '-translate-x-full', collapsed ? 'lg:w-[3.75rem]' : 'lg:w-64']"
           aria-label="Sidebar">
      <div class="flex h-16 shrink-0 items-center gap-2.5 px-3" :class="collapsed ? 'lg:justify-center lg:px-0' : ''">
        <span class="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-brand text-brand-ink"><AppIcon name="bolt" :size="16" /></span>
        <div class="min-w-0" :class="collapsed ? 'lg:hidden' : ''">
          <p class="truncate text-sm font-semibold leading-tight">MCP Hub</p>
          <p class="truncate text-xs text-subtle">Data tools for AI</p>
        </div>
      </div>

      <nav class="flex-1 space-y-4 overflow-y-auto overflow-x-hidden px-2 py-2" aria-label="Main">
        <div v-for="group in groups" :key="group.label">
          <p class="flex h-8 items-center px-2 text-xs font-medium text-subtle" :class="collapsed ? 'lg:sr-only' : ''">{{ group.label }}</p>
          <ul class="space-y-0.5">
            <li v-for="link in group.links" :key="link.to">
              <RouterLink :to="link.to" :title="collapsed ? link.label : undefined"
                          class="flex h-9 items-center gap-2.5 rounded-md px-2.5 text-sm transition-colors"
                          :class="[active(link.to) ? 'bg-muted font-medium text-ink' : 'text-subtle hover:bg-muted hover:text-ink',
                                   collapsed ? 'lg:justify-center lg:px-0' : '']"
                          :aria-current="active(link.to) ? 'page' : undefined">
                <AppIcon :name="link.icon" :size="17" />
                <span class="truncate" :class="collapsed ? 'lg:sr-only' : ''">{{ link.label }}</span>
              </RouterLink>
            </li>
          </ul>
        </div>
      </nav>

    </aside>
    <div v-if="open" class="fixed inset-0 z-20 bg-ink/40 lg:hidden" @click="open = false" />

    <div class="flex min-w-0 flex-1 flex-col">
      <header class="sticky top-0 z-10 flex h-16 shrink-0 items-center gap-3 border-b border-line bg-canvas/95 px-4 backdrop-blur sm:px-6 print:hidden">
        <button class="btn-ghost btn-icon -ml-2" type="button" aria-label="Toggle navigation" @click="toggleSidebar">
          <AppIcon name="panel-left" :size="18" />
        </button>
        <span class="h-4 w-px bg-line" aria-hidden="true" />
        <nav class="flex min-w-0 items-center gap-1.5 text-sm" aria-label="Breadcrumb">
          <span class="hidden text-subtle sm:inline">MCP Hub</span>
          <AppIcon name="chevron-right" :size="14" class="hidden text-subtle sm:block" />
          <RouterLink v-if="nested" :to="section!.to" class="truncate text-subtle hover:text-ink">{{ section!.label }}</RouterLink>
          <span v-else class="truncate font-medium text-ink">{{ section?.label ?? "" }}</span>
          <template v-if="nested">
            <AppIcon name="chevron-right" :size="14" class="text-subtle" />
            <span class="truncate font-medium text-ink">{{ leaf }}</span>
          </template>
        </nav>

        <div class="ml-auto flex items-center gap-1">
          <RouterLink to="/docs/guide" class="btn-ghost btn-sm"><AppIcon name="book" :size="16" /><span class="hidden sm:inline">Docs</span></RouterLink>
          <ThemeSwitch variant="toggle" />
          <div ref="menu" class="relative">
            <button type="button" class="flex items-center gap-2 rounded-md p-1 hover:bg-muted" aria-haspopup="menu" :aria-expanded="menuOpen"
                    aria-label="Account" @click="menuOpen = !menuOpen">
              <span class="avatar">{{ initials }}</span>
            </button>
            <div v-if="menuOpen" role="menu" class="card absolute right-0 top-11 z-40 w-72 p-1 shadow-pop">
              <div class="flex items-center gap-2.5 px-2 py-2">
                <span class="avatar">{{ initials }}</span>
                <div class="min-w-0">
                  <p class="truncate text-sm font-medium">{{ session.user?.email }}</p>
                  <p class="text-xs text-subtle">{{ roleLabel }}</p>
                </div>
              </div>
              <div class="my-1 h-px bg-line" />
              <div class="px-2 py-1.5">
                <p class="mb-1.5 text-xs text-subtle">Theme</p>
                <ThemeSwitch />
              </div>
              <div class="my-1 h-px bg-line" />
              <button type="button" role="menuitem" class="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-muted" @click="signOut">
                <AppIcon name="logout" :size="16" /> Sign out
              </button>
            </div>
          </div>
        </div>
      </header>
      <main ref="content" class="min-h-0 flex-1 overflow-y-auto print:overflow-visible" tabindex="-1" aria-label="Page content">
        <div class="mx-auto max-w-6xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          <RouterView />
        </div>
      </main>
    </div>
  </div>
  <RouterView v-else />
  <ToastHost />
</template>
