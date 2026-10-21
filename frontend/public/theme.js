// Apply the chosen theme before anything renders, so the page never flashes the wrong one.
// A file rather than an inline script, so the Content-Security-Policy can stay script-src 'self'.
try {
  var theme = localStorage.getItem("hub-theme");
  if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
} catch (error) { /* storage blocked: follow the system */ }
