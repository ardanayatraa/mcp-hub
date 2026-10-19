import { computed, ref } from "vue";

// Light, Dark or System. The choice lives in this browser; index.html applies it before the first paint.
export type ThemeChoice = "light" | "dark" | "system";

const KEY = "hub-theme";
const query = typeof window !== "undefined" ? window.matchMedia("(prefers-color-scheme: dark)") : null;

function stored(): ThemeChoice {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

const choice = ref<ThemeChoice>(stored());
const systemDark = ref(query?.matches ?? false);
query?.addEventListener("change", (event) => { systemDark.value = event.matches; });

function apply(value: ThemeChoice) {
  const root = document.documentElement;
  if (value === "system") delete root.dataset.theme;
  else root.dataset.theme = value;
}

export function useTheme() {
  const isDark = computed(() => choice.value === "dark" || (choice.value === "system" && systemDark.value));

  function setTheme(value: ThemeChoice) {
    choice.value = value;
    apply(value);
    try {
      if (value === "system") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, value);
    } catch { /* storage blocked: the choice lasts until the page reloads */ }
  }

  /** One click switches to the other look, whatever the current choice is. */
  function toggle() {
    setTheme(isDark.value ? "light" : "dark");
  }

  return { choice, isDark, setTheme, toggle };
}
