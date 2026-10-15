// Trace review page. Every piece of transcript text goes into the DOM as a
// text node (see h()), never as HTML: the traces hold web pages, emails and
// other people's messages, and none of it may run here.
"use strict";

const token = new URLSearchParams(location.hash.slice(1)).get("t") || "";
const $ = (id) => document.getElementById(id);
const state = { items: [], tally: null, name: "", filter: "unlabeled", current: null, verdict: null, busy: false };

const KIND_ICON = { chat: "forum", task: "schedule", memory: "psychology" };
const TOOL_ICON = { Bash: "terminal", Read: "description", Edit: "edit", MultiEdit: "edit", Write: "edit_document",
  NotebookEdit: "edit_document", Grep: "search", Glob: "folder_open", WebFetch: "travel_explore",
  WebSearch: "travel_explore", Agent: "smart_toy", Task: "smart_toy", Skill: "extension", TodoWrite: "checklist" };
const PROMPT_LABEL = { human: "Alex", slash_command: "Slash command", system_injected: "Routine prompt",
  task_notification: "Background task finished", agent_prompt: "Agent prompt" };
const ENTRYPOINT = { "sdk-cli": "Console or headless", cli: "Terminal", "claude-desktop": "Claude desktop app" };
const EVENT_LABEL = { api_error: "API error, retried", compact_boundary: "Context compacted",
  model_refusal_fallback: "Refusal fallback to another model" };

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
const icon = (name, cls) => h("i", { class: cls }, name);
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

async function api(path, body) {
  const opts = { headers: { "X-Review-Token": token } };
  if (body) {
    opts.method = "POST";
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

const dateFmt = new Intl.DateTimeFormat(undefined, { weekday: "short", month: "numeric", day: "numeric",
  hour: "numeric", minute: "2-digit" });
const when = (ts) => (ts ? dateFmt.format(new Date(ts)) : "");
function duration(a, b) {
  if (!a || !b) return "";
  const min = Math.round((new Date(b) - new Date(a)) / 60000);
  return min < 60 ? `${min} min` : `${Math.floor(min / 60)} h ${min % 60} min`;
}

function banner(message, retry) {
  const b = $("banner");
  b.replaceChildren();
  b.hidden = !message;
  if (!message) return;
  b.append(h("article", { class: "error-container round row" }, icon("error"), h("div", { class: "max" }, message),
    retry ? h("button", { class: "border", onclick: retry }, "Retry") : null));
}

function visible() {
  return state.filter === "all" ? state.items : state.items.filter((i) => !i.verdict || i.id === state.current);
}

function renderQueue() {
  const t = state.tally;
  $("sample-name").textContent = `Sample ${state.name.replace(/^sample-/, "")}`;
  $("progress-text").textContent = `${t.labeled} of ${t.total} labeled`;
  $("progress").max = t.total || 1;
  $("progress").value = t.labeled;
  $("f-unlabeled").querySelector("span").textContent = `Unlabeled · ${t.total - t.labeled}`;
  $("f-unlabeled").classList.toggle("fill", state.filter === "unlabeled");
  $("f-all").classList.toggle("fill", state.filter === "all");
  $("tally").textContent = `Pass ${t.pass} · Fail ${t.fail} · Skip ${t.skip}`;
  const marks = { pass: ["check_circle", "green-text"], fail: ["cancel", "red-text"],
    skip: ["remove_circle_outline", "outline-text"] };
  $("queue").replaceChildren(...visible().map((it) => {
    const [mark, markClass] = marks[it.verdict] || ["radio_button_unchecked", "outline-text"];
    return h("li", { class: it.id === state.current ? "current" : "", "data-id": it.id, onclick: () => openItem(it.id) },
      icon(KIND_ICON[it.stratum] || "help"),
      h("div", { class: "max" },
        h("div", { class: "bold one-line", title: it.label }, it.label),
        h("div", { class: "small-text" }, `${when(it.first_ts)} · ${plural(it.n_tool_calls, "tool")}`,
          it.n_tool_errors ? h("span", { class: "red-text" }, ` · ${it.n_tool_errors} err`) : null)),
      icon(mark, markClass));
  }));
  const cur = $("queue").querySelector("li.current");
  if (cur) cur.scrollIntoView({ block: "nearest" });
}

function longText(text) {
  const div = h("div", { class: "text" }, text);
  if (text.split("\n").length <= 16 && text.length <= 1600) return div;
  div.classList.add("fold");
  const button = h("button", { class: "transparent small" }, "Show all");
  button.addEventListener("click", () => {
    button.textContent = div.classList.toggle("fold") ? "Show all" : "Show less";
  });
  return h("div", {}, div, button);
}

function noteLabel(step) {
  if (step.category === "meta") {
    const skill = /skills\/([^\s/]+)/.exec(step.text);
    return skill ? `Skill loaded: ${skill[1]}` : step.text.split("\n")[0].slice(0, 160);
  }
  if (step.category === "compact_summary") return "Summary written at compaction";
  if (step.category === "local_command") return "Local command output";
  return step.category;
}

function stepRow(step) {
  if (step.type === "tool") {
    const glyph = TOOL_ICON[step.tool] || ((step.tool || "").startsWith("mcp__") ? "extension" : "build");
    let result = step.result === null ? "(no result logged)" : step.result || "(empty result)";
    if (step.result_chars > (step.result || "").length) {
      result += `\n… ${step.result_chars - step.result.length} more characters in the archive`;
    }
    return h("details", { class: `tool-row${step.is_error ? " error" : ""}` },
      h("summary", { class: "none" }, icon(glyph), h("span", { class: "bold" }, step.tool),
        h("span", { class: "summary-text mono" }, step.summary)),
      h("div", { class: "result" }, result));
  }
  if (step.type === "text") {
    return h("details", { class: "tool-row" },
      h("summary", { class: "none" }, icon("chat"), h("span", { class: "bold" }, "MIST"),
        h("span", { class: "summary-text" }, step.text.split("\n")[0])),
      h("div", { class: "result plain" }, step.text));
  }
  if (step.type === "event") {
    return h("div", { class: "tool-row event small-text" }, icon(step.subtype === "api_error" ? "cloud_off" : "compress"),
      EVENT_LABEL[step.subtype] || step.subtype);
  }
  if (step.type === "note" && step.category !== "interrupt") {
    return h("div", { class: "tool-row event small-text" }, icon(step.category === "meta" ? "extension" : "info"),
      noteLabel(step));
  }
  return null;
}

function renderTurn(turn) {
  const box = h("section", { class: "turn" });
  const p = turn.prompt;
  if (p) {
    box.append(h("article", { class: "border round prompt" },
      h("div", { class: "small-text bold primary-text" }, `${PROMPT_LABEL[p.category] || p.category} · ${when(p.ts)}`),
      longText(p.text)));
  }
  const rows = turn.steps.map(stepRow).filter(Boolean);
  if (rows.length) {
    const events = turn.steps.filter((s) => s.type === "event").length;
    box.append(h("details", { class: "turn-tools" },
      h("summary", { class: "none" }, h("div", { class: "row small-text" }, icon("build"),
        h("span", {}, plural(turn.n_tools, "tool call"),
          turn.n_errors ? h("span", { class: "red-text bold" }, ` · ${plural(turn.n_errors, "error")}`) : null,
          events ? ` · ${plural(events, "event")}` : null),
        h("div", { class: "max" }), icon("expand_more"))),
      h("div", { class: "tool-list border round" }, rows)));
  }
  for (const step of turn.steps) {
    if (step.type === "note" && step.category === "interrupt") {
      box.append(h("div", { class: "note-row interrupt row small-text" }, icon("front_hand"), "You interrupted MIST here"));
    }
  }
  if (turn.reply) {
    box.append(h("article", { class: "round surface-container reply" }, h("div", { class: "small-text bold" }, "MIST"),
      longText(turn.reply)));
  }
  return box;
}

function renderTrace(trace, item) {
  const chips = [
    ...trace.models.map((m) => h("span", { class: "chip" }, m)),
    h("span", { class: "chip" }, icon("person"), `${plural(item.n_human_prompts, "prompt")} from you`),
    h("span", { class: "chip" }, icon("build"), plural(item.n_tool_calls, "tool call")),
    item.n_tool_errors ? h("span", { class: "chip error-container" }, icon("error"), plural(item.n_tool_errors, "error")) : null,
    typeof trace.cost_usd === "number" ? h("span", { class: "chip" }, icon("payments"), `$${trace.cost_usd.toFixed(2)}`) : null,
  ];
  const header = h("article", { class: "round border" },
    h("h5", { class: "small" }, trace.title || item.label),
    h("div", { class: "small-text" },
      [when(trace.first_ts), duration(trace.first_ts, trace.last_ts), ENTRYPOINT[trace.entrypoint] || trace.entrypoint, item.stratum].filter(Boolean).join(" · ")),
    h("div", { class: "row wrap chips" }, chips));
  const turns = trace.turns.length ? trace.turns.map(renderTurn) : [h("p", {}, "This session has no turns.")];
  $("trace").replaceChildren(header, ...turns);
  $("trace-pane").scrollTop = 0;
}

function setVerdict(verdict) {
  state.verdict = verdict;
  for (const b of document.querySelectorAll("[data-verdict]")) {
    const on = b.dataset.verdict === verdict;
    b.classList.toggle("border", !on);
    b.classList.toggle("error", on && verdict === "fail");
    b.classList.toggle("secondary", on && verdict === "skip");
  }
}

async function openItem(id) {
  if (state.busy) return;
  const item = state.items.find((i) => i.id === id);
  if (!item) return;
  state.current = id;
  setVerdict(item.verdict);
  $("note").value = item.note || "";
  $("saved-state").textContent = item.verdict ? `Saved as ${item.verdict}. A new save replaces it.` : "";
  banner(null);
  renderQueue();
  $("trace").replaceChildren();
  $("loading").hidden = false;
  try {
    const trace = await api(`/api/trace?id=${encodeURIComponent(id)}`);
    if (state.current === id) renderTrace(trace, item);
  } catch (err) {
    if (state.current === id) banner(`Could not load this trace: ${err.message}`, () => openItem(id));
  } finally {
    if (state.current === id) $("loading").hidden = true;
  }
}

function showDone() {
  state.current = null;
  renderQueue();
  const t = state.tally;
  $("trace").replaceChildren(h("article", { class: "round border" },
    h("h5", {}, "All sessions in this sample have a label"),
    h("p", {}, `Pass ${t.pass} · Fail ${t.fail} · Skip ${t.skip}`),
    h("p", {}, "Tell MIST in the chat: labels done.")));
}

function nextUnlabeled() {
  const k = state.items.findIndex((i) => i.id === state.current);
  for (let step = 1; step <= state.items.length; step++) {
    const it = state.items[(k + step) % state.items.length];
    if (!it.verdict) return openItem(it.id);
  }
  showDone();
}

function move(delta) {
  const list = visible();
  const it = list[list.findIndex((i) => i.id === state.current) + delta];
  if (it) openItem(it.id);
}

async function save() {
  if (!state.current || state.busy) return;
  if (!state.verdict) {
    banner("Pick Pass, Fail or Skip first (P, F or S).");
    return;
  }
  state.busy = true;
  $("save").disabled = true;
  try {
    const res = await api("/api/label", { id: state.current, verdict: state.verdict, note: $("note").value });
    const item = state.items.find((i) => i.id === state.current);
    item.verdict = res.label.verdict;
    item.note = res.label.note;
    state.tally = res.tally;
    banner(null);
    state.busy = false;
    nextUnlabeled();
  } catch (err) {
    banner(`The save failed and your note is still here: ${err.message}`, save);
  } finally {
    state.busy = false;
    $("save").disabled = false;
  }
}

function toggleAllTools() {
  const all = [...document.querySelectorAll("details.turn-tools")];
  const open = all.some((d) => !d.open);
  for (const d of all) d.open = open;
}

document.addEventListener("keydown", (e) => {
  if (document.activeElement === $("note")) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      save();
    } else if (e.key === "Escape") {
      $("note").blur();
    }
    return;
  }
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const key = e.key.toLowerCase();
  const actions = { p: () => setVerdict("pass"), f: () => setVerdict("fail"), s: () => setVerdict("skip"),
    n: () => $("note").focus(), j: () => move(1), k: () => move(-1), e: toggleAllTools, enter: save };
  if (actions[key]) {
    e.preventDefault();
    actions[key]();
  }
});

function followTheme() {
  const dark = matchMedia("(prefers-color-scheme: dark)");
  const apply = () => {
    document.body.classList.toggle("dark", dark.matches);
    document.body.classList.toggle("light", !dark.matches);
  };
  apply();
  dark.addEventListener("change", apply);
}

async function init() {
  if (!token) {
    banner("Open the link that bin/traces review prints. The part after # is the access token.");
    return;
  }
  try {
    const data = await api("/api/sample");
    state.items = data.items;
    state.tally = data.tally;
    state.name = data.name;
  } catch (err) {
    banner(`Could not reach the review server: ${err.message}`, init);
    return;
  }
  banner(null);
  if (!state.items.length) {
    renderQueue();
    $("trace").replaceChildren(h("article", { class: "round border" }, h("h5", {}, "This sample has no sessions"),
      h("p", {}, "Make one in Terminal: bin/traces sample --name sample-1")));
    return;
  }
  const first = state.items.find((i) => !i.verdict);
  if (first) openItem(first.id);
  else showDone();
}

followTheme();
$("f-unlabeled").addEventListener("click", () => { state.filter = "unlabeled"; renderQueue(); });
$("f-all").addEventListener("click", () => { state.filter = "all"; renderQueue(); });
for (const b of document.querySelectorAll("[data-verdict]")) b.addEventListener("click", () => setVerdict(b.dataset.verdict));
$("save").addEventListener("click", save);
init();
