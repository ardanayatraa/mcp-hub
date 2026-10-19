import type { RouterConfig } from "@nuxt/schema";

export default {
  scrollBehavior: () => ({ top: 0 }),
  routes: (pages) => [
    ...pages,
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
} satisfies RouterConfig;
