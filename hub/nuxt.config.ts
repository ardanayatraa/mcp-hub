// MCP Hub, JavaScript edition. One Nuxt app: the admin UI (app/) renders in the browser,
// and Nitro (server/) serves the admin API, the MCP endpoint and the chat API.
const themeScript = `try {
  var theme = localStorage.getItem("hub-theme");
  if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
} catch (error) { /* storage blocked: follow the system */ }`;

export default defineNuxtConfig({
  compatibilityDate: "2026-10-01",
  // The admin UI is behind sign-in, so it renders in the browser only.
  ssr: false,
  spaLoadingTemplate: false,
  devtools: { enabled: false },
  telemetry: false,
  modules: ["@pinia/nuxt"],
  css: ["~/style.css"],
  postcss: { plugins: { tailwindcss: {}, autoprefixer: {} } },
  app: {
    head: {
      title: "MCP Hub",
      htmlAttrs: { lang: "en" },
      meta: [{ name: "color-scheme", content: "light dark" }],
      link: [{
        rel: "icon",
        href: "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Crect width='24' height='24' rx='6' fill='%2318181b'/%3E%3Cpath d='M13 4 6 14h5l-1 6 7-10h-5z' fill='white'/%3E%3C/svg%3E",
      }],
      // Apply the chosen theme before anything renders, so the page never flashes the wrong one.
      script: [{ innerHTML: themeScript }],
    },
  },
  // node:sqlite has no unprefixed name, so Nitro's built-in list misses it.
  nitro: { rollupConfig: { external: ["node:sqlite"] } },
  // Strict, without unchecked-index errors: the same bar the UI was written against.
  typescript: { tsConfig: { compilerOptions: { noUncheckedIndexedAccess: false } } },
  routeRules: {
    "/**": { headers: { "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer" } },
  },
});
