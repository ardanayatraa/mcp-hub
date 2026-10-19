<script setup lang="ts">
import { useTheme, type ThemeChoice } from "@/utils/theme";

// Light, Dark or System as three small buttons ("full"), or one button that flips between light and dark ("toggle").
withDefaults(defineProps<{ variant?: "full" | "toggle" }>(), { variant: "full" });
const { choice, isDark, setTheme, toggle } = useTheme();
const OPTIONS: { value: ThemeChoice; label: string; icon: string }[] = [
  { value: "light", label: "Light", icon: "sun" },
  { value: "dark", label: "Dark", icon: "moon" },
  { value: "system", label: "System", icon: "monitor" },
];
</script>

<template>
  <button v-if="variant === 'toggle'" type="button" class="btn-ghost btn-icon"
          :aria-label="isDark ? 'Switch to light mode' : 'Switch to dark mode'" :title="isDark ? 'Light mode' : 'Dark mode'" @click="toggle">
    <AppIcon :name="isDark ? 'sun' : 'moon'" :size="17" />
  </button>
  <div v-else class="segmented w-full" role="radiogroup" aria-label="Theme">
    <button v-for="option in OPTIONS" :key="option.value" type="button" role="radio" class="segmented-item flex-1 justify-center"
            :aria-checked="choice === option.value" :aria-pressed="choice === option.value" @click="setTheme(option.value)">
      <AppIcon :name="option.icon" :size="14" /> {{ option.label }}
    </button>
  </div>
</template>
