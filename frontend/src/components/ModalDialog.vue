<script setup lang="ts">
import { onBeforeUnmount, onMounted } from "vue";

withDefaults(defineProps<{ title: string; wide?: boolean }>(), { wide: false });
const emit = defineEmits<{ close: [] }>();

function onKey(event: KeyboardEvent) {
  if (event.key === "Escape") emit("close");
}
onMounted(() => window.addEventListener("keydown", onKey));
onBeforeUnmount(() => window.removeEventListener("keydown", onKey));
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-40 flex items-end justify-center bg-black/60 p-0 sm:items-center sm:p-4"
         @mousedown.self="emit('close')">
      <section role="dialog" aria-modal="true" :aria-label="title"
               class="max-h-[92vh] w-full overflow-y-auto rounded-t-xl border border-line bg-surface shadow-pop sm:rounded-xl"
               :class="wide ? 'sm:max-w-3xl' : 'sm:max-w-lg'">
        <header class="flex items-center justify-between gap-4 px-6 pb-2 pt-5">
          <h2 class="text-lg leading-tight">{{ title }}</h2>
          <button class="btn-ghost btn-sm" type="button" aria-label="Close" @click="emit('close')"><AppIcon name="x" /></button>
        </header>
        <div class="px-6 py-3"><slot /></div>
        <footer v-if="$slots.footer" class="flex flex-wrap justify-end gap-2 px-6 pb-5 pt-3">
          <slot name="footer" />
        </footer>
      </section>
    </div>
  </Teleport>
</template>
