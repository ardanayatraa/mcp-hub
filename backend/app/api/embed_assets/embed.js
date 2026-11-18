/* MCP Hub embedded chat loader. Usage:
   <script src="https://YOUR-HUB/api/embed/v1/embed.js" data-widget="w_..." async></script>
   Adds a chat button; the chat itself runs in an iframe served by the Hub.
   Add data-token="<the signed-in user's app token>" to sign the user in automatically. */
(function () {
  "use strict";
  var script = document.currentScript;
  if (!script) return;
  var id = script.getAttribute("data-widget");
  if (!id || !/^w_[A-Za-z0-9_-]{8,36}$/.test(id) || window["__hubEmbed_" + id]) return;
  window["__hubEmbed_" + id] = true;
  var base = new URL(script.src).origin;
  var pageUrl = base + "/api/embed/v1/w/" + encodeURIComponent(id);
  // Optional: when the page is already signed in to the app, its server puts a short-lived app token here
  // and the chat signs in by itself. It travels in the iframe's fragment, which is never sent to a server.
  var hostToken = script.getAttribute("data-token");

  function start(config) {
    var accent = /^#[0-9a-fA-F]{6}$/.test(config.accent || "") ? config.accent : "#2563eb";
    var side = config.position === "left" ? "left" : "right";
    var host = document.createElement("div");
    host.setAttribute("data-hub-embed", id);
    var root = host.attachShadow ? host.attachShadow({ mode: "closed" }) : host;
    root.innerHTML =
      "<style>" +
      ".b{position:fixed;bottom:20px;" + side + ":20px;width:56px;height:56px;border-radius:50%;border:0;cursor:pointer;" +
      "background:" + accent + ";color:#fff;box-shadow:0 6px 20px rgba(0,0,0,.25);display:flex;align-items:center;" +
      "justify-content:center;z-index:2147483646;transition:transform .15s}.b:hover{transform:scale(1.06)}" +
      ".b:focus-visible{outline:3px solid #fff;outline-offset:2px}" +
      ".p{position:fixed;bottom:88px;" + side + ":20px;width:380px;height:600px;max-height:calc(100vh - 110px);" +
      "border-radius:16px;overflow:hidden;box-shadow:0 12px 40px rgba(0,0,0,.28);z-index:2147483647;display:none;background:#fff}" +
      ".p.o{display:block}.p iframe{width:100%;height:100%;border:0}" +
      "@media (max-width:480px){.p{left:0;right:0;bottom:0;width:100%;height:100%;max-height:none;border-radius:0}" +
      ".b.h{display:none}}</style>" +
      "<div class='p' role='dialog' aria-label='Chat'></div>" +
      "<button class='b' type='button' aria-label='Open chat' aria-expanded='false'>" +
      "<svg width='26' height='26' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' " +
      "stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 " +
      "0 0 1 2-2h14a2 2 0 0 1 2 2z'/></svg></button>";
    var panel = root.querySelector(".p");
    var button = root.querySelector(".b");
    var frame = null;
    function toggle(open) {
      if (open && !frame) {
        frame = document.createElement("iframe");
        frame.src = pageUrl + (hostToken ? "#host=" + encodeURIComponent(hostToken) : "");
        frame.title = config.title || "Chat";
        frame.setAttribute("allow", "clipboard-write");
        panel.appendChild(frame);
      }
      panel.classList.toggle("o", open);
      button.classList.toggle("h", open);
      button.setAttribute("aria-expanded", open ? "true" : "false");
      button.setAttribute("aria-label", open ? "Close chat" : "Open chat");
    }
    button.addEventListener("click", function () { toggle(!panel.classList.contains("o")); });
    window.addEventListener("message", function (event) {
      if (event.origin === base && event.data && event.data.hubEmbed === id && event.data.action === "close") toggle(false);
    });
    (document.body || document.documentElement).appendChild(host);
  }

  fetch(pageUrl + "/config", { credentials: "omit" })
    .then(function (response) { return response.ok ? response.json() : null; })
    .then(function (body) { if (body && body.data) start(body.data); })
    .catch(function () { /* the chat stays hidden when the Hub cannot be reached */ });
})();
