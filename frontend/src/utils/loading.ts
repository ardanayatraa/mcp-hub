import { onUnmounted, ref, watch, type Ref } from "vue";

/** True once `active` has stayed true for `delayMs`, so quick requests never flash a "still waiting" notice. */
export function useSlowFlag(active: Ref<boolean>, delayMs = 2500): Ref<boolean> {
  const slow = ref(false);
  let timer: ReturnType<typeof setTimeout> | undefined;
  watch(active, (on) => {
    clearTimeout(timer);
    slow.value = false;
    if (on) timer = setTimeout(() => { slow.value = true; }, delayMs);
  }, { immediate: true });
  onUnmounted(() => clearTimeout(timer));
  return slow;
}
