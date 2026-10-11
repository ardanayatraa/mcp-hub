import { createPinia } from "pinia";
import { createApp } from "vue";

import App from "./App.vue";
import AppIcon from "./components/AppIcon.vue";
import CopyButton from "./components/CopyButton.vue";
import router from "./router";
import "./style.css";

createApp(App)
  .use(createPinia())
  .use(router)
  .component("AppIcon", AppIcon)
  .component("CopyButton", CopyButton)
  .mount("#app");
