import { defineStore } from "pinia";

export interface Toast { id: number; tone: "ok" | "bad" | "info"; message: string }

let next = 1;

export const useToast = defineStore("toast", {
  state: () => ({ items: [] as Toast[] }),
  actions: {
    push(tone: Toast["tone"], message: string) {
      const id = next++;
      this.items.push({ id, tone, message });
      window.setTimeout(() => this.dismiss(id), tone === "bad" ? 7000 : 3500);
    },
    ok(message: string) { this.push("ok", message); },
    error(message: string) { this.push("bad", message); },
    info(message: string) { this.push("info", message); },
    dismiss(id: number) { this.items = this.items.filter((item) => item.id !== id); },
  },
});
