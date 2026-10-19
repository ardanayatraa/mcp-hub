import { defineStore } from "pinia";

import { api } from "@/services/api";

export interface AdminUser {
  id: string;
  email: string;
  role: string;
  mfa_enabled: boolean;
}

interface LoginResult {
  user?: AdminUser;
  csrf_token?: string;
  mfa_required?: boolean;
  enrollment_required?: boolean;
  mfa_token?: string;
  otpauth_uri?: string;
}

export const useSession = defineStore("session", {
  state: () => ({
    user: null as AdminUser | null,
    ready: false,
  }),
  getters: {
    canWrite: (state) => ["super_admin", "app_admin"].includes(state.user?.role ?? ""),
    isSuper: (state) => state.user?.role === "super_admin",
  },
  actions: {
    async login(email: string, password: string) {
      const data = await api<LoginResult>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
      if (data.csrf_token && data.user) {
        sessionStorage.setItem("hub_csrf", data.csrf_token);
        this.user = data.user;
      }
      return data;
    },
    async confirmMfa(mfaToken: string, code: string) {
      const data = await api<{ user: AdminUser; csrf_token: string }>("/auth/mfa", {
        method: "POST",
        body: JSON.stringify({ mfa_token: mfaToken, code }),
      });
      sessionStorage.setItem("hub_csrf", data.csrf_token);
      this.user = data.user;
    },
    async restore() {
      try {
        const data = await api<AdminUser & { csrf_token: string }>("/auth/me");
        sessionStorage.setItem("hub_csrf", data.csrf_token);
        this.user = data;
      } catch {
        this.user = null;
        sessionStorage.removeItem("hub_csrf");
      } finally {
        this.ready = true;
      }
    },
    async logout() {
      try {
        await api("/auth/logout", { method: "POST" });
      } finally {
        this.user = null;
        sessionStorage.removeItem("hub_csrf");
      }
    },
  },
});
