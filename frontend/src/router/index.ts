import { createRouter, createWebHistory } from "vue-router";

import { useSession } from "@/stores/session";

const router = createRouter({
  history: createWebHistory(),
  scrollBehavior: () => ({ top: 0 }),
  routes: [
    { path: "/login", component: () => import("@/views/LoginView.vue"), meta: { public: true } },
    { path: "/", component: () => import("@/views/OverviewView.vue") },
    { path: "/apps", component: () => import("@/views/AppsView.vue") },
    { path: "/apps/new", component: () => import("@/views/AppConnectView.vue"), meta: { write: true } },
    { path: "/apps/:id", component: () => import("@/views/AppDetailView.vue") },
    { path: "/tools", component: () => import("@/views/ToolsView.vue") },
    { path: "/tools/new", component: () => import("@/views/ToolCreateView.vue"), meta: { write: true } },
    { path: "/tools/report", component: () => import("@/views/ReportPlaygroundView.vue"), meta: { write: true } },
    { path: "/tools/:id", component: () => import("@/views/ToolDetailView.vue") },
    { path: "/access", component: () => import("@/views/AccessView.vue") },
    { path: "/providers", component: () => import("@/views/ProvidersView.vue") },
    { path: "/activity", component: () => import("@/views/ActivityView.vue") },
    { path: "/settings", component: () => import("@/views/SettingsView.vue"), meta: { superAdmin: true } },
    { path: "/assistant", component: () => import("@/views/AssistantView.vue") },
    { path: "/docs/guide", component: () => import("@/views/UserGuideView.vue") },
    { path: "/docs/laravel", component: () => import("@/views/LaravelGuideView.vue") },
    { path: "/docs", redirect: "/docs/guide" },
    // Earlier page addresses.
    { path: "/connectors/new", redirect: "/apps/new" },
    { path: "/connectors", redirect: "/apps" },
    { path: "/modules", redirect: "/apps" },
    { path: "/audit", redirect: "/activity" },
    { path: "/security", redirect: "/access" },
    { path: "/operations", redirect: "/settings" },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});

router.beforeEach(async (to) => {
  const session = useSession();
  if (!session.ready) await session.restore();
  if (!to.meta.public && !session.user) return { path: "/login", query: to.path !== "/" ? { next: to.fullPath } : {} };
  if (to.path === "/login" && session.user) return "/";
  if (to.meta.superAdmin && session.user?.role !== "super_admin") return "/";
  if (to.meta.write && session.user?.role === "auditor") return "/";
  return true;
});

export default router;
