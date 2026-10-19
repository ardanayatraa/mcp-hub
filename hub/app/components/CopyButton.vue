<script setup lang="ts">
import { ref } from "vue";

const props = withDefaults(defineProps<{ text: string; label?: string }>(), { label: "Copy" });
const copied = ref(false);

async function copy() {
  try {
    await navigator.clipboard.writeText(props.text);
  } catch {
    const area = document.createElement("textarea");
    area.value = props.text;
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
  copied.value = true;
  window.setTimeout(() => (copied.value = false), 1500);
}
</script>

<template>
  <button type="button" class="btn-secondary btn-sm" @click="copy">
    <AppIcon :name="copied ? 'check' : 'copy'" :size="14" /> {{ copied ? "Copied" : label }}
  </button>
</template>
