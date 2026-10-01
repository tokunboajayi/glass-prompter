"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const API = "/api/v1";
  let es = null, state = {}, editingId = null, toastTimer = 0, searchTimer = 0, armedDelete = null;

  // ---------------------------------------------------------------- helpers
  function toast(msg, ok) {
    const t = $("toast");
    t.textContent = msg;
    t.className = "show " + (ok ? "ok" : "bad");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.className = ""; }, 2600);
  }
  function setConn(text, cls) {
    const p = $("conn");
    p.className = "pill " + (cls || "");
    p.lastElementChild.textContent = text;
  }
  async function api(path, opts = {}) {
    const init = { credentials: "same-origin", headers: {}, ...opts };
    if (opts.json !== undefined) {
      init.body = JSON.stringify(opts.json);
      init.headers["Content-Type"] = "application/json";
      delete init.json;
    }
    const r = await fetch(API + path, init);
    let data = {};
    try { data = await r.json(); } catch (e) { /* empty body */ }
    if (r.status === 401 && path !== "/session") { showPair(); throw new Error("unauthorized"); }
    if (!r.ok) throw new Error((data.error && data.error.message) || ("Error " + r.status));
    return data;
  }
  const quiet = (e) => { if (e.message !== "unauthorized") toast(e.message, false); };
  function ago(ts) {
    if (!ts) return "";
    const s = Math.max(0, Date.now() / 1000 - ts);
    if (s < 60) return "just now";
    if (s < 3600) return Math.floor(s / 60) + " min ago";
    if (s < 86400) return Math.floor(s / 3600) + " h ago";
    return Math.floor(s / 86400) + " d ago";
  }
  function words(text) {
    return text.split("\n").filter((l) => !/^\s*\[.*\]\s*$/.test(l)).join(" ").split(/\s+/).filter(Boolean).length;
  }
  function mmss(sec) { sec = Math.round(sec); return Math.floor(sec / 60) + ":" + String(sec % 60).padStart(2, "0"); }

  // ---------------------------------------------------------------- pairing
  function showPair() {
    if (es) { es.close(); es = null; }
    $("app").hidden = true;
    $("pairView").hidden = false;
    setConn("Not paired", "warn");
    setTimeout(() => $("pin").focus(), 50);
  }
  async function pair(pin) {
    try {
      await api("/session", { method: "POST", json: { pin } });
      history.replaceState(null, "", "/");          // never leave the PIN in the address bar
      start();
    } catch (e) {
      $("pin").value = "";
      toast(e.message, false);
      showPair();
    }
  }
  $("pairForm").addEventListener("submit", (e) => { e.preventDefault(); pair($("pin").value.trim()); });

  // ---------------------------------------------------------------- live state
  function render(s) {
    state = s || {};
    const voice = !!s.voice_follow;
    $("stateText").textContent = s.counting ? "Starting..." : s.listening ? "Listening" : s.playing ? "Playing" : "Paused";
    $("meta").textContent = (voice ? (s.live_wpm ? "You: " + s.live_wpm + " wpm" : "Voice Follow")
      : (s.wpm || 0) + " wpm") + " \u00b7 " + (s.left || "0:00") + " left";
    $("voiceBtn").classList.toggle("on", voice);
    $("voiceText").textContent = voice ? (s.listening ? "Listening" : "Voice Follow on") : "Voice Follow off";
    const secs = s.sections || [];
    $("secWrap").hidden = secs.length === 0;
    const sl = $("secList");
    if (sl.dataset.key !== secs.join("|")) {
      sl.dataset.key = secs.join("|");
      sl.textContent = "";
      secs.forEach((t) => { const c = document.createElement("span"); c.textContent = t; sl.appendChild(c); });
    }
    $("scriptTitle").textContent = s.script ? s.script.title : "";
    $("prog").style.width = Math.round((s.progress || 0) * 100) + "%";
    $("queued").hidden = !s.queued;
    const active = s.playing || s.counting || s.listening;
    $("ppIcon").textContent = active ? "\u275a\u275a" : "\u25b6";
    $("ppText").textContent = voice ? (s.listening ? "Stop listening" : "Start listening") : (active ? "Pause" : "Play");
    if (!s.window_visible) setConn("Prompter hidden", "warn");
    else if (s.capture_hidden) setConn("Hidden from share", "ok");
    else setConn("VISIBLE in share", "bad");
    document.querySelectorAll(".item").forEach((li) =>
      li.classList.toggle("current", !!(s.script && String(s.script.id) === li.dataset.id)));
  }
  function start() {
    $("pairView").hidden = true;
    $("app").hidden = false;
    if (es) es.close();
    es = new EventSource(API + "/events");
    es.addEventListener("state", (ev) => { try { render(JSON.parse(ev.data)); } catch (e) { /* ignore */ } });
    es.addEventListener("logout", () => { toast("PIN changed. Pair again.", false); showPair(); });
    es.onerror = () => {
      setConn("Reconnecting", "warn");
      api("/state").then(render).catch(() => {});     // 401 -> pair screen; otherwise EventSource retries
    };
    loadList();
  }

  // ---------------------------------------------------------------- tabs
  document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".tabs button").forEach((x) => {
      const on = x === b;
      x.setAttribute("aria-selected", on);
      $("tab-" + x.dataset.tab).hidden = !on;
    });
    if (b.dataset.tab === "library") loadList();
  }));
  function showTab(name) { document.querySelector('.tabs button[data-tab="' + name + '"]').click(); }

  // ---------------------------------------------------------------- remote
  document.querySelectorAll("[data-action]").forEach((b) => b.addEventListener("click", () => {
    if (navigator.vibrate) navigator.vibrate(10);
    api("/control", { method: "POST", json: { action: b.dataset.action } }).catch(quiet);
  }));

  // ---------------------------------------------------------------- library
  async function loadList() {
    try {
      const q = $("search").value.trim();
      const data = await api("/scripts" + (q ? "?q=" + encodeURIComponent(q) : ""));
      const ul = $("list");
      ul.textContent = "";
      data.scripts.forEach((s) => ul.appendChild(item(s)));
      $("empty").hidden = data.scripts.length > 0;
    } catch (e) { quiet(e); }
  }
  function button(label, cls, fn) {
    const b = document.createElement("button");
    b.className = "btn " + cls;
    b.type = "button";
    b.textContent = label;
    b.addEventListener("click", fn);
    return b;
  }
  function item(s) {
    const li = document.createElement("li");
    li.className = "item";
    li.dataset.id = s.id;
    if (state.script && state.script.id === s.id) li.classList.add("current");
    const h = document.createElement("h3"); h.textContent = s.title;
    const p = document.createElement("p"); p.textContent = s.words + " words · " + ago(s.last_used || s.updated);
    const row = document.createElement("div"); row.className = "row";
    row.appendChild(button("Load", "primary", () =>
      api("/scripts/" + s.id + "/load", { method: "POST" }).then(() => toast("Loaded on the prompter", true)).catch(quiet)));
    row.appendChild(button("Edit", "", () => edit(s.id)));
    const del = button("Delete", "danger", () => {
      if (armedDelete !== del) {
        if (armedDelete) armedDelete.textContent = "Delete";
        armedDelete = del; del.textContent = "Sure?";
        setTimeout(() => { if (armedDelete === del) { del.textContent = "Delete"; armedDelete = null; } }, 3000);
        return;
      }
      armedDelete = null;
      api("/scripts/" + s.id, { method: "DELETE" }).then(() => { toast("Deleted", true); loadList(); }).catch(quiet);
    });
    row.appendChild(del);
    li.append(h, p, row);
    return li;
  }
  $("search").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(loadList, 250); });

  // ---------------------------------------------------------------- write / edit
  function setEditing(s) {
    editingId = s ? s.id : null;
    $("editing").textContent = s ? "Editing: " + s.title : "New script";
    $("newBtn").hidden = !s;
    $("title").value = s ? s.title : "";
    $("body").value = s ? s.body : "";
    count();
  }
  async function edit(id) {
    try { setEditing(await api("/scripts/" + id)); showTab("write"); } catch (e) { quiet(e); }
  }
  function count() {
    const n = words($("body").value);
    $("count").textContent = n + " words · about " + mmss(n / 150 * 60) + " at 150 wpm";
  }
  async function save(load) {
    const body = $("body").value;
    if (!body.trim()) return toast("The script is empty", false);
    const json = { title: $("title").value, body, load };
    try {
      const s = editingId
        ? await api("/scripts/" + editingId, { method: "PUT", json })
        : await api("/scripts", { method: "POST", json });
      setEditing(s);
      toast(load ? "Saved and sent to the prompter" : "Saved", true);
    } catch (e) { quiet(e); }
  }
  $("body").addEventListener("input", count);
  $("save").addEventListener("click", () => save(false));
  $("saveLoad").addEventListener("click", () => save(true));
  $("newBtn").addEventListener("click", () => setEditing(null));
  $("file").addEventListener("change", async (e) => {
    const f = e.target.files[0];
    e.target.value = "";
    if (!f) return;
    try {
      const r = await fetch(API + "/upload?name=" + encodeURIComponent(f.name), {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/octet-stream" }, body: await f.arrayBuffer() });
      const data = await r.json().catch(() => ({}));
      if (r.status === 401) return showPair();
      if (!r.ok) throw new Error((data.error && data.error.message) || "Upload failed");
      toast("Uploaded " + f.name, true);
      setEditing(data);
    } catch (err) { toast(err.message, false); }
  });

  // ---------------------------------------------------------------- boot
  const k = new URLSearchParams(location.search).get("k");
  if (k) pair(k);
  else api("/state").then((s) => { render(s); start(); }).catch(() => {});
})();
