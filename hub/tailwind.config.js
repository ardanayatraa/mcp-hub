/** @type {import('tailwindcss').Config} */
const token = (name) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: { relative: true, files: ["./app/**/*.{vue,ts}"] },
  theme: {
    extend: {
      colors: {
        canvas: token("canvas"),
        surface: token("surface"),
        sidebar: token("sidebar"),
        muted: token("muted"),
        line: token("line"),
        ink: token("ink"),
        subtle: token("subtle"),
        brand: { DEFAULT: token("brand"), soft: token("brand-soft"), ink: token("brand-ink") },
        ok: { DEFAULT: token("ok"), soft: token("ok-soft") },
        warn: { DEFAULT: token("warn"), soft: token("warn-soft") },
        bad: { DEFAULT: token("bad"), soft: token("bad-soft") },
        chart: { 1: token("chart-1"), 2: token("chart-2") },
      },
      fontFamily: {
        sans: ["Inter", "Segoe UI", "system-ui", "-apple-system", "sans-serif"],
        mono: ["JetBrains Mono", "Cascadia Code", "ui-monospace", "monospace"],
      },
      boxShadow: {
        card: "0 1px 2px 0 rgb(0 0 0 / 0.05)",
        pop: "0 10px 30px -10px rgb(0 0 0 / 0.25), 0 4px 6px -4px rgb(0 0 0 / 0.1)",
      },
    },
  },
  plugins: [],
};
