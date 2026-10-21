import { onBeforeUnmount, onMounted } from "vue";

// Provider APIs do not notify the Hub when their catalog changes. Check again while
// a model picker is visible, and when the user returns to the tab.
export function useVisibleModelRefresh(refresh: () => void) {
  const intervalMs = 60_000;
  let lastRequest = 0;
  let timer: number | undefined;
  const markRequested = () => { lastRequest = Date.now(); };
  const check = () => {
    if (document.visibilityState === "visible" && Date.now() - lastRequest >= intervalMs) refresh();
  };

  onMounted(() => {
    timer = window.setInterval(check, 15_000);
    window.addEventListener("focus", check);
    document.addEventListener("visibilitychange", check);
  });
  onBeforeUnmount(() => {
    window.clearInterval(timer);
    window.removeEventListener("focus", check);
    document.removeEventListener("visibilitychange", check);
  });
  return markRequested;
}
