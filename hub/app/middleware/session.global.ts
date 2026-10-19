import { useSession } from "@/stores/session";

// Every page needs a signed-in admin except those marked public; some need a role.
export default defineNuxtRouteMiddleware(async (to) => {
  const session = useSession();
  if (!session.ready) await session.restore();
  if (!to.meta.public && !session.user) {
    return navigateTo({ path: "/login", query: to.path !== "/" ? { next: to.fullPath } : {} });
  }
  if (to.path === "/login" && session.user) return navigateTo("/");
  if (to.meta.superAdmin && session.user?.role !== "super_admin") return navigateTo("/");
  if (to.meta.write && session.user?.role === "auditor") return navigateTo("/");
});
