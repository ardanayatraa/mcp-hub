// Components registered globally in main.ts.
import AppIcon from "./components/AppIcon.vue";
import CopyButton from "./components/CopyButton.vue";

declare module "vue" {
  export interface GlobalComponents {
    AppIcon: typeof AppIcon;
    CopyButton: typeof CopyButton;
  }
}

export {};
