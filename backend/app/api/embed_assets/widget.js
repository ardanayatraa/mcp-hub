(function () {
  "use strict";
  var app = document.getElementById("app");
  var id = app.getAttribute("data-widget");
  var api = "/api/embed/v1/w/" + encodeURIComponent(id);
  var storeKey = "hubEmbed:" + id;
  var lang = (navigator.language || "en").toLowerCase().indexOf("id") === 0 ? "id" : "en";
  var T = {
    en: { signIn: "Sign in", signInTo: "Sign in to %s", signInHint: "Use your %s account. Only you can see your data.",
      signOut: "Sign out", working: "Signing in…", type: "Type a message…", unavailable: "This chat is not available right now.",
      failed: "Something went wrong. Try again.", reading: "Reading %s", preview: "Admin preview as %s · read-only",
      signedAs: "Signed in as %s", expired: "Your session ended. Sign in again.", offline: "Can't reach the chat. Check your connection." },
    id: { signIn: "Masuk", signInTo: "Masuk ke %s", signInHint: "Gunakan akun %s kamu. Hanya kamu yang bisa melihat datamu.",
      signOut: "Keluar", working: "Sedang masuk…", type: "Ketik pesan…", unavailable: "Chat ini sedang tidak tersedia.",
      failed: "Terjadi kesalahan. Coba lagi.", reading: "Membaca %s", preview: "Pratinjau admin sebagai %s · hanya baca",
      signedAs: "Masuk sebagai %s", expired: "Sesi kamu berakhir. Silakan masuk lagi.", offline: "Chat tidak bisa dihubungi. Periksa koneksimu." }
  }[lang];
  function t(key, value) { return T[key].replace("%s", value == null ? "" : value); }

  var main = document.getElementById("main");
  var composer = document.getElementById("composer");
  var input = document.getElementById("input");
  var send = document.getElementById("send");
  var signout = document.getElementById("signout");
  var banner = document.getElementById("banner");
  var config = null;
  var history = [];
  var busy = false;

  // An admin preview arrives in the fragment (never sent to a server) and lives only in memory.
  var preview = null;
  var match = /(?:^|[#&])preview=([^&]+)/.exec(location.hash);
  if (match) preview = decodeURIComponent(match[1]);
  // The page the chat sits on is already signed in to the app: it hands over the user's app token.
  var host = null;
  var hostMatch = /(?:^|[#&])host=([^&]+)/.exec(location.hash);
  if (hostMatch) host = decodeURIComponent(hostMatch[1]);
  var hostTries = 0;
  var hostError = "";
  if (match || hostMatch) {
    try { history_replace(); } catch (e) { /* ignore */ }
  }
  function history_replace() { window.history.replaceState(null, "", location.pathname); }
  function stored() { try { return localStorage.getItem(storeKey); } catch (e) { return null; } }
  function store(value) { try { value ? localStorage.setItem(storeKey, value) : localStorage.removeItem(storeKey); } catch (e) { /* private mode */ } }
  function token() { return preview || stored(); }
  function headers(json) {
    var h = { Accept: "application/json" };
    if (json) h["Content-Type"] = "application/json";
    var value = token();
    if (value) h.Authorization = "Bearer " + value;
    return h;
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }
  function escapeHtml(text) {
    return text.replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; });
  }
  function inline(text) {
    return escapeHtml(text).replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/`([^`]+)`/g, "<code>$1</code>");
  }
  function render(text) {
    return text.split(/\n{2,}/).map(function (block) {
      var lines = block.split("\n");
      if (lines.every(function (line) { return /^\s*[-*]\s+/.test(line); })) {
        return "<ul>" + lines.map(function (line) { return "<li>" + inline(line.replace(/^\s*[-*]\s+/, "")) + "</li>"; }).join("") + "</ul>";
      }
      return "<p>" + lines.map(inline).join("<br>") + "</p>";
    }).join("");
  }
  function scroll() { main.scrollTop = main.scrollHeight; }

  document.getElementById("close").addEventListener("click", function () {
    if (window.parent !== window) window.parent.postMessage({ hubEmbed: id, action: "close" }, "*");
  });
  signout.addEventListener("click", function () {
    fetch(api + "/sign-out", { method: "POST", headers: headers(false) }).catch(function () {});
    store(null);
    history = [];
    load();
  });

  // Signs in with the host page's token unless this browser already holds a session for that same token.
  function hostSignIn() {
    if (!host || preview) return Promise.resolve();
    var key = storeKey + ":host";
    var fingerprint = host.slice(-16);
    var last = null;
    try { last = localStorage.getItem(key); } catch (e) { /* private mode */ }
    if (hostTries === 0 && stored() && last === fingerprint) return Promise.resolve();
    return fetch(api + "/sign-in-token", { method: "POST", headers: headers(true), body: JSON.stringify({ token: host }) })
      .then(function (response) { return response.json(); })
      .then(function (body) {
        if (!body.success) throw new Error((body.error && body.error.message) || T.failed);
        store(body.data.session);
        try { localStorage.setItem(key, fingerprint); } catch (e) { /* private mode */ }
        hostError = "";
      })
      .catch(function (exc) { store(null); hostError = (exc && exc.message) || T.failed; });
  }

  function load() {
    main.innerHTML = "";
    main.appendChild(el("p", "muted center", "…"));
    composer.hidden = true;
    hostSignIn()
      .then(function () { return fetch(api + "/config", { headers: headers(false) }); })
      .then(function (response) { return response.json(); })
      .then(function (body) {
        if (!body || !body.success) throw new Error("config");
        config = body.data;
        document.documentElement.style.setProperty("--accent", config.accent);
        document.getElementById("title").textContent = config.title;
        document.title = config.title;
        if (!config.available) return message(T.unavailable);
        if (!config.user) {
          if (preview) { preview = null; return message(T.expired); }
          // A stored session the Hub no longer knows: sign in again from the host token once.
          if (host && hostTries === 0) { hostTries = 1; store(null); return load(); }
          return signInForm(hostError || undefined);
        }
        chat();
      })
      .catch(function () { message(T.offline); });
  }

  function message(text) {
    main.innerHTML = "";
    main.appendChild(el("p", "muted center", text));
    document.getElementById("user").textContent = "";
    signout.hidden = true;
  }

  function signInForm(note) {
    document.getElementById("user").textContent = "";
    signout.hidden = true;
    banner.hidden = true;
    main.innerHTML = "";
    var form = el("form", "card");
    form.appendChild(el("h2", null, t("signInTo", config.app)));
    form.appendChild(el("p", "muted", t("signInHint", config.app)));
    if (note) form.appendChild(el("p", "error", note));
    config.sign_in.forEach(function (field) {
      var label = el("label", null, field.label);
      var box = document.createElement("input");
      box.name = field.name;
      box.type = field.type;
      box.required = true;
      box.maxLength = 300;
      box.autocomplete = field.type === "password" ? "current-password" : (field.type === "email" ? "username" : "off");
      label.appendChild(box);
      form.appendChild(label);
    });
    var error = el("p", "error");
    error.hidden = true;
    form.appendChild(error);
    var submit = el("button", "primary", T.signIn);
    submit.type = "submit";
    form.appendChild(submit);
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var fields = {};
      config.sign_in.forEach(function (field) { fields[field.name] = form.elements[field.name].value; });
      submit.disabled = true;
      submit.textContent = T.working;
      error.hidden = true;
      fetch(api + "/sign-in", { method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ fields: fields }) })
        .then(function (response) { return response.json(); })
        .then(function (body) {
          if (!body.success) throw new Error((body.error && body.error.message) || T.failed);
          store(body.data.session);
          load();
        })
        .catch(function (exc) {
          error.textContent = exc.message || T.failed;
          error.hidden = false;
          submit.disabled = false;
          submit.textContent = T.signIn;
        });
    });
    main.appendChild(form);
    var first = form.querySelector("input");
    if (first) first.focus();
  }

  function chat() {
    var name = config.user.name;
    document.getElementById("user").textContent = name ? t("signedAs", name) : "";
    banner.hidden = !config.user.preview;
    banner.textContent = config.user.preview ? t("preview", name || "—") : "";
    signout.hidden = !!config.user.preview || !!host;
    signout.textContent = T.signOut;
    main.innerHTML = "";
    if (config.welcome_message) main.appendChild(bubble("bot", config.welcome_message));
    if (config.suggestions && config.suggestions.length && !history.length) {
      var chips = el("div", "chips");
      config.suggestions.forEach(function (text) {
        var chip = el("button", "chip", text);
        chip.type = "button";
        chip.addEventListener("click", function () { chips.remove(); ask(text); });
        chips.appendChild(chip);
      });
      main.appendChild(chips);
    }
    history.forEach(function (item) { main.appendChild(bubble(item.role === "user" ? "user" : "bot", item.text)); });
    composer.hidden = false;
    input.placeholder = T.type;
    input.focus();
    scroll();
  }

  function bubble(kind, text) {
    var node = el("div", "msg " + kind);
    if (kind === "bot") node.innerHTML = render(text); else node.textContent = text;
    return node;
  }

  input.addEventListener("input", function () { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 120) + "px"; });
  input.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); composer.requestSubmit(); }
  });
  composer.addEventListener("submit", function (event) {
    event.preventDefault();
    var text = input.value.trim();
    if (text && !busy) ask(text);
  });

  function ask(text) {
    busy = true;
    send.disabled = true;
    input.value = "";
    input.style.height = "auto";
    var chips = main.querySelector(".chips");
    if (chips) chips.remove();
    main.appendChild(bubble("user", text));
    var tools = el("div", "tools");
    var answer = bubble("bot", "…");
    main.appendChild(tools);
    main.appendChild(answer);
    scroll();
    var full = "";
    var chipsById = {};
    var sent = history.slice(-40);
    fetch(api + "/turn", { method: "POST", headers: headers(true),
      body: JSON.stringify({ message: text, history: sent, locale: lang }) })
      .then(function (response) {
        if (!response.ok) {
          return response.json().then(function (body) {
            var error = (body && body.error) || {};
            if (response.status === 401) { store(null); preview = null; signInForm(T.expired); throw null; }
            throw new Error(error.message || T.failed);
          });
        }
        var reader = response.body.getReader();
        var decoder = new TextDecoder();
        var buffer = "";
        function handle(block) {
          var event = "message", data = "";
          block.split("\n").forEach(function (line) {
            if (line.indexOf("event:") === 0) event = line.slice(6).trim();
            else if (line.indexOf("data:") === 0) data += line.slice(5).trim();
          });
          if (!data) return;
          var payload;
          try { payload = JSON.parse(data); } catch (e) { return; }
          if (event === "text") {
            full += payload.delta || "";
            answer.innerHTML = render(full);
          } else if (event === "tool") {
            var chip = chipsById[payload.id];
            if (!chip) { chip = el("span", "tool"); chipsById[payload.id] = chip; tools.appendChild(chip); }
            chip.textContent = t("reading", payload.title || payload.name);
            chip.className = "tool" + (payload.status === "running" ? " run" : "");
          } else if (event === "notice" && payload.message) {
            main.insertBefore(el("p", "foot", payload.message), answer.nextSibling);
          } else if (event === "error") {
            throw new Error(payload.message || T.failed);
          }
          scroll();
        }
        function pump() {
          return reader.read().then(function (part) {
            if (part.done) return;
            buffer += decoder.decode(part.value, { stream: true });
            var index;
            while ((index = buffer.indexOf("\n\n")) >= 0) {
              var block = buffer.slice(0, index);
              buffer = buffer.slice(index + 2);
              if (block && block[0] !== ":") handle(block);
            }
            return pump();
          });
        }
        return pump();
      })
      .then(function () {
        if (!full) answer.remove();
        history.push({ role: "user", text: text });
        if (full) history.push({ role: "assistant", text: full });
      })
      .catch(function (exc) {
        if (exc === null) return;
        answer.remove();
        main.appendChild(el("div", "msg err", (exc && exc.message) || T.failed));
      })
      .then(function () { busy = false; send.disabled = false; scroll(); });
  }

  load();
})();
