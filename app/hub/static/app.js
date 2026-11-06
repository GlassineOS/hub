// SPDX-License-Identifier: GPL-2.0-or-later
import { html, render, useState, useEffect, useRef, useCallback, useMemo } from "./vendor/preact-htm.js";
import { Terminal } from "./vendor/xterm.mjs";
import { FitAddon } from "./vendor/addon-fit.mjs";

class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

async function api(path, { method = "GET", body } = {}) {
  const response = await fetch(`/api/${path}`, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  const isJson = (response.headers.get("content-type") || "").includes("json");
  const data = isJson && text ? JSON.parse(text) : text;
  if (!response.ok) {
    if (response.status === 401 && path !== "login") window.dispatchEvent(new Event("hub-logout"));
    throw new ApiError((data && data.error) || `HTTP ${response.status}`, response.status);
  }
  return data;
}

const post = (path, body = {}) => api(path, { method: "POST", body });
// What a session is about: one item, or the whole project.
const alsoCovers = (a) => (a.also_numbers || []).map((n) => ` #${n}`).join("");
const whereFrom = (a) => (a.repo ? (a.number ? `${a.repo}#${a.number}${alsoCovers(a)}` : a.repo) : "the whole project");
const params = (o) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(o)) if (v) p.set(k, v);
  const s = p.toString();
  return s ? `?${s}` : "";
};
const count = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const seconds = (date) => (Date.now() - new Date(date).getTime()) / 1000;

function ago(date) {
  if (!date) return "";
  const s = seconds(date);
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 129600) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

function age(date) {
  if (!date) return "";
  const s = seconds(date);
  if (s < 90) return "now";
  if (s < 5400) return `${Math.round(s / 60)} m`;
  if (s < 129600) return `${Math.round(s / 3600)} h`;
  if (s < 1209600) return `${Math.round(s / 86400)} d`;
  return `${Math.round(s / 604800)} w`;
}

const hash = (path, query = {}) => `#/${path}${params(query)}`;

// --- hash routing -------------------------------------------------------------
function readRoute() {
  const [path, query] = location.hash.replace(/^#\/?/, "").split("?");
  return { path: path || "overview", query: Object.fromEntries(new URLSearchParams(query || "")) };
}
function useRoute() {
  const [route, set] = useState(readRoute());
  useEffect(() => {
    const on = () => set(readRoute());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

// --- loading ---------------------------------------------------------------------
// A failed reload keeps what the last good one read, with the error beside it: when hubd goes away the views stay as
// they were and the header's banner says so. Data read for other deps (another issue, say) is not kept.
function useLoad(loader, deps, every) {
  const [state, set] = useState({ loading: true });
  const seq = useRef(0);
  const loadedFor = useRef(null);
  const sig = deps.map(String).join("\u0000");
  const reload = useCallback(async () => {
    const mine = ++seq.current;
    set((s) => ({ ...s, loading: true }));
    try {
      const data = await loader();
      if (mine === seq.current) { loadedFor.current = sig; set({ data, loading: false }); }
    } catch (error) {
      if (mine === seq.current) set((s) => ({ ...(loadedFor.current === sig ? s : {}), error: error.message, loading: false }));
    }
  }, deps);
  useEffect(() => {
    reload();
    if (!every) return undefined;
    const timer = setInterval(() => { if (!document.hidden) reload(); }, every);
    return () => clearInterval(timer);
  }, [reload, every]);
  return { ...state, reload };
}

// One action at a time, and its error stays visible.
function useAct(after) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const run = async (fn) => {
    setBusy(true); setError(null);
    try {
      const result = await fn();
      if (after) await after(result);
      return result;
    } catch (e) {
      setError(e.message);
      return undefined;
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, run };
}

const useSessions = () => useLoad(() => api("shells").catch(() => []), [], 15000);

const Err = ({ text }) => (text ? html`<div class="error" role="alert">${text}</div>` : null);
const Eyebrow = ({ children, soft }) => html`<span class="eyebrow ${soft ? "soft" : ""}">${children}</span>`;

function Confirm({ title, text, label, danger, onYes, onNo }) {
  const ref = useRef();
  useEffect(() => { ref.current.showModal(); }, []);
  return html`<dialog ref=${ref} onClose=${onNo}>
    <h2>${title}</h2><p>${text}</p>
    <div class="row">
      <button class=${danger ? "danger" : "primary"} onClick=${onYes}>${label}</button>
      <button onClick=${onNo}>Cancel</button>
    </div></dialog>`;
}

function useConfirm() {
  const [ask, setAsk] = useState(null);
  const confirm = (options, then) => setAsk({ ...options, then });
  const dialog = ask && html`<${Confirm} ...${ask}
    onYes=${() => { const t = ask.then; setAsk(null); t(); }} onNo=${() => setAsk(null)} />`;
  return [confirm, dialog];
}

// --- icons -----------------------------------------------------------------------
function StateIcon({ kind, label }) {
  const a = label ? { role: "img", "aria-label": label } : { "aria-hidden": "true" };
  const ink = "currentColor";
  if (kind === "fail") {
    return html`<svg width="16" height="16" viewBox="0 0 16 16" ...${a}><rect x="2" y="2" width="12" height="12" rx="2" fill="var(--signal)" stroke=${ink} stroke-width="1.5" /><path d="M5.5 5.5l5 5M10.5 5.5l-5 5" stroke="var(--paper)" stroke-width="1.5" /></svg>`;
  }
  if (kind === "run") return html`<svg width="16" height="16" viewBox="0 0 16 16" ...${a}><circle cx="8" cy="8" r="6" fill="none" stroke=${ink} stroke-width="1.5" stroke-dasharray="3 2.5" /></svg>`;
  if (kind === "pass") return html`<svg width="16" height="16" viewBox="0 0 16 16" ...${a}><circle cx="8" cy="8" r="6" fill="none" stroke=${ink} stroke-width="1.5" /><path d="M5 8.2l2 2 4-4.2" fill="none" stroke=${ink} stroke-width="1.5" /></svg>`;
  return html`<svg width="16" height="16" viewBox="0 0 16 16" ...${a}><circle cx="8" cy="8" r="6" fill="none" stroke=${ink} stroke-width="1.5" /></svg>`;
}
const TermIcon = () => html`<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M7 9l3 3-3 3M12 15h5" /></svg>`;
const SearchIcon = () => html`<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M20 20l-4-4" /></svg>`;
const Chevron = ({ right }) => html`<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d=${right ? "M6 3l5 5-5 5" : "M10 3L5 8l5 5"} /></svg>`;

// --- Markdown: built as elements, so nothing in a body can become HTML ------------
// showUrls: every address in the open, for text you're about to publish. Nothing here hides any other text.
function inline(text, showUrls) {
  const out = [];
  const pattern = /`([^`]+)`|\*\*([^*]+)\*\*|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[^\s)<>]+)/g;
  let at = 0;
  for (let m = pattern.exec(text); m; m = pattern.exec(text)) {
    const image = showUrls && m[3] && text[m.index - 1] === "!";
    if (m.index > at) out.push(text.slice(at, image ? m.index - 1 : m.index));
    if (image) out.push(html`<span class="mono md-url">image ${m[3]}: ${m[4]}</span>`);
    else if (m[3] && showUrls) out.push(html`<a href=${m[4]} target="_blank" rel="noreferrer noopener">${m[3]}</a>`, " ", html`<span class="mono md-url">(${m[4]})</span>`);
    else if (m[1]) out.push(html`<code>${m[1]}</code>`);
    else if (m[2]) out.push(html`<b>${m[2]}</b>`);
    else if (m[3]) out.push(html`<a href=${m[4]} target="_blank" rel="noreferrer noopener">${m[3]}</a>`);
    else out.push(html`<a href=${m[5]} target="_blank" rel="noreferrer noopener">${m[5]}</a>`);
    at = m.index + m[0].length;
  }
  if (at < text.length) out.push(text.slice(at));
  return out;
}

function Md({ text, showUrls }) {
  const blocks = useMemo(() => {
    const out = [];
    const lines = String(text || "").replaceAll("\r\n", "\n").split("\n");
    for (let i = 0; i < lines.length;) {
      const line = lines[i];
      if (line.startsWith("```")) {
        const code = [];
        for (i += 1; i < lines.length && !lines[i].startsWith("```"); i += 1) code.push(lines[i]);
        i += 1;
        out.push(html`<pre><code>${code.join("\n")}</code></pre>`);
      } else if (/^#{1,6}\s/.test(line)) {
        out.push(html`<h3>${inline(line.replace(/^#+\s+/, ""), showUrls)}</h3>`);
        i += 1;
      } else if (/^\s*[-*]\s/.test(line) || /^\s*\d+\.\s/.test(line)) {
        const ordered = /^\s*\d+\.\s/.test(line);
        const items = [];
        for (; i < lines.length && (/^\s*[-*]\s/.test(lines[i]) || /^\s*\d+\.\s/.test(lines[i])); i += 1) {
          items.push(html`<li>${inline(lines[i].replace(/^\s*(?:[-*]|\d+\.)\s+/, ""), showUrls)}</li>`);
        }
        out.push(ordered ? html`<ol>${items}</ol>` : html`<ul>${items}</ul>`);
      } else if (line.startsWith(">")) {
        const quote = [];
        for (; i < lines.length && lines[i].startsWith(">"); i += 1) quote.push(lines[i].replace(/^>\s?/, ""));
        out.push(html`<blockquote>${inline(quote.join(" "), showUrls)}</blockquote>`);
      } else if (!line.trim()) {
        i += 1;
      } else {
        const para = [];
        for (; i < lines.length && lines[i].trim() && !/^(```|#{1,6}\s|>|\s*[-*]\s|\s*\d+\.\s)/.test(lines[i]); i += 1) para.push(lines[i]);
        out.push(html`<p>${inline(para.join(" "), showUrls)}</p>`);
      }
    }
    return out;
  }, [text, showUrls]);
  return blocks.length ? blocks : html`<p class="soft">(no description)</p>`;
}

// --- shared components ---------------------------------------------------------------
// The building blocks every view uses (spec 002): ItemPill, PersonaBadge, SessionChip, RepoPicker,
// ItemPicker. State is in words, outline or icon, never colour alone; yellow only for what waits for you.

// Item references (002 FR-001): repo#N for issues, pull requests and roadmap items, workflow #N for runs.
const KIND_WORD = { issue: "Issue", pr: "Pull request", run: "Run", roadmap: "Roadmap item" };
const KIND_TAB = { issue: "issues", pr: "prs", run: "actions", roadmap: "issues" };
const ref = (item) => (item.kind === "run" ? `${item.workflow || "run"} #${item.number}` : `${item.repo}#${item.number}`);
const itemHref = (item) => hash("work", { tab: KIND_TAB[item.kind] || "issues", at: item.repo, item: item.number });
// The ItemPill state of a row as GitHub or the work store gives it.
function pillState(kind, row) {
  if (!row) return undefined;
  if (kind === "run") {
    if (row.status && row.status !== "completed") return "running";
    const c = row.conclusion;
    if (["failure", "timed_out", "startup_failure", "action_required"].includes(c)) return "failing";
    if (c === "success") return "passed";
    return c === "cancelled" ? "cancelled" : c === "skipped" ? "skipped" : "closed";
  }
  const state = String(row.state || "").toUpperCase();
  if (state === "MERGED") return "merged";
  if (state === "CLOSED") return "closed";
  if (kind === "pr" && row.isDraft) return "draft";
  if (kind === "pr" && row.checks === "failing") return "failing";
  if (kind === "pr" && row.checks === "pending") return "running";
  return "open";
}
// 002 FR-003, 001 FR-012: the outline tells the state, with the icon and the words; the fill never does.
const PILL_STATE = {
  open: ["open", "sev-low", null], draft: ["draft", "sev-info", null], merged: ["merged", "sev-low", "pass"],
  closed: ["closed", "sev-low", null], failing: ["failing", "sev-high", "fail"], running: ["running", "sev-info", "run"],
  passed: ["passed", "sev-low", "pass"], cancelled: ["cancelled", "sev-low", null], skipped: ["skipped", "sev-low", null],
};

function KindIcon({ kind }) {
  const a = { width: 14, height: 14, viewBox: "0 0 16 16", fill: "none", stroke: "currentColor", "stroke-width": 1.6, "aria-hidden": "true" };
  if (kind === "pr") return html`<svg ...${a}><circle cx="4.5" cy="3.5" r="1.8" /><circle cx="4.5" cy="12.5" r="1.8" /><circle cx="11.5" cy="12.5" r="1.8" /><path d="M4.5 5.3v5.4M11.5 10.7V7a2.5 2.5 0 0 0-2.5-2.5H7" /></svg>`;
  if (kind === "run") return html`<svg ...${a}><circle cx="8" cy="8" r="6" /><path d="M6.5 5.5v5l4-2.5z" /></svg>`;
  if (kind === "roadmap") return html`<svg ...${a}><path d="M4 14V2.5M4 3h8l-2 3 2 3H4" /></svg>`;
  return html`<svg ...${a}><circle cx="8" cy="8" r="6" /><circle cx="8" cy="8" r="1.4" fill="currentColor" /></svg>`;
}

// href: where it opens when the place showing it keeps more in the address (Work's list scope).
// plain: not a link, for a pill inside a list option. removable: a remove control beside it (002 FR-004).
function ItemPill({ kind, repo, number, title, state, workflow, href, plain, removable, onRemove }) {
  const item = { kind, repo, number, workflow };
  const [word, outline, icon] = PILL_STATE[state] || [null, "sev-low", null];
  const name = `${KIND_WORD[kind] || "Item"} ${ref(item)}${title ? `: ${title}` : ""}${word ? `, ${word}` : ""}`;
  const body = html`<${KindIcon} kind=${kind} />${icon && html`<${StateIcon} kind=${icon} />`}<span class="ref">${ref(item)}</span>${title && html`<span class="title">${title}</span>`}`;
  const cls = `itempill ${outline} ${state || ""}`;
  const pill = plain ? html`<span class=${cls} title=${name}><span class="sr">${name}</span><span aria-hidden="true" class="row" style="gap: 6px; flex-wrap: nowrap; min-width: 0">${body}</span></span>`
    : html`<a class=${cls} href=${href || itemHref(item)} aria-label=${name} title=${name}>${body}</a>`;
  if (!removable) return pill;
  return html`<span class="pillwrap">${pill}<button type="button" class="remove" aria-label=${`Remove ${ref(item)}`} onClick=${onRemove}>×</button></span>`;
}

// Persona families (002 FR-011, 002 FR-012); the tints are CSS tokens.
const FAMILIES = [["build", "Build"], ["review", "Review"], ["investigate", "Investigate"], ["write", "Write"], ["organise", "Organise"]];
const FAMILY_WORD = Object.fromEntries(FAMILIES);
const personaOf = (agent) => (agent ? { id: agent.persona, name: agent.persona_name || agent.persona, initials: agent.initials, family: agent.family } : null);

// persona: {id, name, initials, family}, or null for a plain shell (002 FR-014). The Steward always draws its own S (002 FR-013).
// hidden: beside words that already say who it is.
function PersonaBadge({ persona, hidden }) {
  const a = (label) => (hidden ? { "aria-hidden": "true" } : { role: "img", "aria-label": label, title: label });
  if (!persona) return html`<span class="pbadge shell" ...${a("Plain shell")}>${">_"}</span>`;
  if (persona.id === STEWARD) return html`<span class="pbadge steward" ...${a("Steward")}>S</span>`;
  const name = persona.name || persona.id;
  const family = FAMILY_WORD[persona.family] ? persona.family : "unknown";
  const initials = persona.initials || String(persona.id || "?").slice(0, 2).toUpperCase();
  return html`<span class="pbadge ${family}" ...${a(name)}>${initials}</span>`;
}

// 002 FR-015: wherever badges are listed.
function FamilyLegend() {
  return html`<ul class="legend" aria-label="What the badge colours mean">
    ${FAMILIES.map(([id, word]) => html`<li><span class="pbadge ${id}" aria-hidden="true"></span>${word}</li>`)}
    <li><${PersonaBadge} persona=${{ id: STEWARD }} hidden />Steward</li>
    <li><${PersonaBadge} persona=${null} hidden />Plain shell</li></ul>`;
}

// 002 FR-016: RUNNING (idle counts: it's at its prompt), WAITING, DONE, ATTACHED.
function sessionState(session, pending) {
  const a = session.agent;
  if (a && a.ended) return "done";
  if ((a && a.waiting) || pending > 0) return "waiting";
  if (session.attached > 0) return "attached";
  return "running";
}

// 002 FR-019: every session that covers the item, or has a pull request for it. item: {object|kind, repo, number}.
// covers come from hubd (old sessions: their number and also_numbers, folded there); prs from the session's own branch.
function sessionsOn(item, sessions) {
  const kind = item.object || item.kind;
  const same = (x) => x && x.repo === item.repo && String(x.number) === String(item.number);
  return (sessions || []).filter((s) => {
    const a = s.agent;
    if (!a) return false;
    const covers = a.covers || (a.repo && a.number ? [{ repo: a.repo, number: a.number }, ...(a.also_numbers || []).map((n) => ({ repo: a.repo, number: n }))] : []);
    return (a.object === kind && covers.some(same)) || (kind === "pr" && (a.prs || []).some(same));
  });
}

// pending: how many things of this session wait for you, when the place knows. onOpen opens it in place
// (002 FR-018); otherwise it links to href, or to the session under Sessions.
function SessionChip({ session, pending, onOpen, href }) {
  const a = session.agent;
  const state = sessionState(session, pending);
  const waits = state === "waiting";
  const word = waits && pending > 0 ? `${pending} waiting` : state.toUpperCase();
  const said = waits ? (pending > 0 ? `waiting for you, ${count(pending, "thing")}` : "waiting for you")
    : state === "running" && a && a.idle ? "running, idle at its prompt" : state;
  const label = `Session ${session.name}, ${a ? a.persona_name || a.persona : "plain shell"}, ${said}`;
  const attrs = { class: `sesschip ${state}`, "data-waits": waits ? "" : undefined, "aria-label": label, title: label };
  const body = html`<${PersonaBadge} persona=${personaOf(a)} hidden /><span class="name">${session.name}</span><span class="word">${word}</span>`;
  return onOpen ? html`<button type="button" ...${attrs} onClick=${onOpen}>${body}</button>`
    : html`<a ...${attrs} href=${href || hash("shells", { name: session.name })}>${body}</a>`;
}

// A combobox's keys (002 FR-010): arrows walk, Enter picks, Esc closes. Shared by both pickers.
function listKeys(e, { size, active, setActive, pick, close, open = true }) {
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    if (size) setActive((active + (e.key === "ArrowDown" ? 1 : size - 1)) % size);
  } else if (e.key === "Home" || e.key === "End") {
    if (size) { e.preventDefault(); setActive(e.key === "Home" ? 0 : size - 1); }
  } else if (e.key === "Enter") {
    e.preventDefault();
    pick();
  } else if (e.key === "Escape" && open) {
    // Only when there is a list to close: otherwise Esc belongs to what's around the picker, a dialog's cancel included.
    e.preventDefault();
    e.stopPropagation();
    close();
  }
}

let pickerSeq = 0;
const usePickerId = () => useRef(`picker-${++pickerSeq}`).current;
// Closes a picker's list on a click outside it.
// Focus moving out of the picker (Tab, or a click elsewhere; lower-case "onfocusout" so Preact listens for "focusout") closes its list, so it never covers what's below (002 FR-010).
const leaves = (box, close) => (e) => { if (box.current && !box.current.contains(e.relatedTarget)) close(); };

function useOutside(ref, open, close) {
  useEffect(() => {
    if (!open) return undefined;
    const on = (e) => { if (ref.current && !ref.current.contains(e.target)) close(); };
    document.addEventListener("mousedown", on);
    return () => document.removeEventListener("mousedown", on);
  }, [open]);
}

// Recents and pins, per viewer, in this browser only (001 R2). A blocked storage just means none.
const PICKS_KEY = "repo-picker";
const MAX_RECENT = 5;
function readPicks() {
  try {
    const v = JSON.parse(localStorage.getItem(PICKS_KEY)) || {};
    return { recent: Array.isArray(v.recent) ? v.recent : [], pins: Array.isArray(v.pins) ? v.pins : [] };
  } catch { return { recent: [], pins: [] }; }
}
function writePicks(picks) {
  try { localStorage.setItem(PICKS_KEY, JSON.stringify(picks)); } catch { /* it only helps */ }
}

// value: a name ("" for all) or, with many, a list of names. groups: /api/overview's layers.
// 002 FR-005–002 FR-007: type to filter; pinned and recent first, then by layer; more than 3 chosen shows a count.
function RepoPicker({ value, onChange, many, allowAll, groups, label = "Repository" }) {
  const id = usePickerId();
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const [active, setActive] = useState(0);
  const [picks, setPicks] = useState(readPicks);
  const box = useRef();
  const button = useRef();
  const input = useRef();
  const chosen = many ? value || [] : value ? [value] : [];
  const summary = !chosen.length ? (allowAll ? "All repositories" : "Choose…")
    : chosen.length > 3 ? `${chosen.length} repos` : chosen.join(", ");
  const known = (groups || []).flatMap((g) => g.repos.map((r) => r.name));
  const needle = filter.trim().toLowerCase();
  const fits = (name) => !needle || name.toLowerCase().includes(needle);
  const sections = [];
  const seen = new Set();
  const add = (title, names) => {
    const rows = names.filter((n) => known.includes(n) && !seen.has(n) && fits(n));
    rows.forEach((n) => seen.add(n));
    if (rows.length) sections.push([title, rows]);
  };
  add("Pinned", picks.pins);
  add("Recent", picks.recent);
  for (const g of groups || []) add(g.title, g.repos.map((r) => r.name));
  const all = allowAll && (!needle || "all repositories".includes(needle));
  const options = [...(all ? [""] : []), ...sections.flatMap(([, rows]) => rows)];
  const at = Math.min(active, Math.max(options.length - 1, 0));
  const optionId = (i) => `${id}-o${i}`;
  useEffect(() => { if (open && input.current) input.current.focus(); }, [open]);
  const close = (refocus = true) => { setOpen(false); setFilter(""); setActive(0); if (refocus && button.current) button.current.focus(); };
  useOutside(box, open, () => close(false));
  const remember = (name) => {
    const next = { ...picks, recent: [name, ...picks.recent.filter((n) => n !== name)].slice(0, MAX_RECENT) };
    setPicks(next); writePicks(next);
  };
  const choose = (name) => {
    if (name === undefined) return;
    if (name) remember(name);
    if (!many) { onChange(name); close(); return; }
    onChange(!name ? [] : chosen.includes(name) ? chosen.filter((n) => n !== name) : [...chosen, name]);
  };
  const activeName = options[at];
  const pinned = activeName && picks.pins.includes(activeName);
  const togglePin = () => {
    const next = { ...picks, pins: pinned ? picks.pins.filter((n) => n !== activeName) : [...picks.pins, activeName] };
    setPicks(next); writePicks(next);
  };
  const option = (name, i) => {
    const selected = name ? chosen.includes(name) : !chosen.length;
    return html`<div role="option" id=${optionId(i)} aria-selected=${selected ? "true" : "false"} data-active=${i === at ? "" : undefined}
      onMouseDown=${(e) => e.preventDefault()} onClick=${() => { setActive(i); choose(name); }}>
      <span class="tick" aria-hidden="true">${selected ? "✓" : ""}</span>${name || "All repositories"}${name && picks.pins.includes(name) ? html`<span class="small soft"> · pinned</span>` : ""}</div>`;
  };
  let index = all ? 1 : 0;
  return html`<div class="picker" ref=${box} onfocusout=${open ? leaves(box, () => close(false)) : undefined}>
    <button type="button" class="picker-button" ref=${button} aria-haspopup="listbox" aria-expanded=${open ? "true" : "false"}
      aria-label=${`${label}: ${summary}`} onClick=${() => (open ? close() : setOpen(true))}><span>${summary}</span><span aria-hidden="true">▾</span></button>
    ${open && html`<div class="pop">
      <input role="combobox" ref=${input} aria-expanded="true" aria-controls=${`${id}-list`} aria-autocomplete="list"
        aria-activedescendant=${options.length ? optionId(at) : undefined} aria-label=${`Filter: ${label}`} placeholder="Type to filter"
        value=${filter} onInput=${(e) => { setFilter(e.target.value); setActive(0); }}
        onKeyDown=${(e) => listKeys(e, { size: options.length, active: at, setActive, pick: () => choose(options[at]), close })} />
      <div role="listbox" id=${`${id}-list`} aria-label=${label} aria-multiselectable=${many ? "true" : undefined}>
        ${all && option("", 0)}
        ${sections.map(([title, rows]) => html`<div role="group" aria-label=${title}><span class="eyebrow soft" aria-hidden="true">${title}</span>
          ${rows.map((name) => option(name, index++))}</div>`)}
        ${!options.length && html`<p class="small soft" style="padding: 8px">No repository matches “${filter}”.</p>`}</div>
      <div class="foot"><span class="small soft">${many ? `${chosen.length} chosen` : ""}</span>
        <span class="row" style="gap: 6px">${activeName && html`<button type="button" class="plain" onClick=${togglePin}>${pinned ? `Unpin ${activeName}` : `Pin ${activeName}`}</button>`}
        ${many && html`<button type="button" class="plain" onClick=${() => close()}>Done</button>`}</span></div></div>`}
  </div>`;
}

// What was typed, when every word of it is a reference: repo#N, or #N or N with one repository.
// null: it's words to search for. outside: references to a repository not among those chosen.
function typedRefs(text, repos) {
  const tokens = text.split(/[\s,]+/).filter(Boolean);
  if (!tokens.length || !tokens.every((t) => /^(?:[A-Za-z0-9._-]+#|#)?\d+$/.test(t))) return null;
  const refs = [];
  const outside = [];
  for (const t of tokens) {
    const [named, n] = t.includes("#") ? t.split("#") : ["", t];
    const repo = named || (repos.length === 1 ? repos[0] : "");
    if (!repo || (repos.length && !repos.includes(repo))) outside.push(t);
    else refs.push({ repo, number: Number(n) });
  }
  return { refs, outside };
}

// The search rows that count for what is typed now: a reply for other words (an older one, or one still on its way)
// shows nothing and can't be picked.
function currentRows(found, words) {
  return found.words === words ? found.rows : [];
}

// 002 FR-008–002 FR-010: by reference or by words, across the chosen repositories (none: all of them).
// kind: "issue" or "pr" (the work store holds no runs). Each pick goes to onPick; many keeps the words and the list
// open for the next, without what was just picked. exclude: refs (repo#N) already chosen.
function ItemPicker({ repos = [], kind, many, onPick, exclude = [], label = "Find an item" }) {
  const id = usePickerId();
  const [text, setText] = useState("");
  const [active, setActive] = useState(0);
  const [found, setFound] = useState({ words: "", rows: [], error: null });
  const box = useRef();
  const words = text.trim();
  const refs = typedRefs(words, repos);
  const byRef = refs !== null;
  const typed = byRef ? refs.refs.map((r) => ({ ...r, kind: kind || "issue" })) : [];
  useEffect(() => {
    if (byRef || words.length < 2) { setFound({ words, rows: [], error: null }); return undefined; }
    let cancelled = false;  // a reply for words that have since changed is dropped, not shown
    const timer = setTimeout(async () => {
      try {
        const r = await api(`work/search${params({ q: words, kind, repo: repos.length === 1 ? repos[0] : undefined, k: 12 })}`);
        const rows = r.results.filter((x) => !repos.length || repos.includes(x.repo))
          .map((x) => ({ kind: x.kind, repo: x.repo, number: x.number, title: x.title, state: pillState(x.kind, x.row || x) }));
        if (!cancelled) setFound({ words, rows, error: null });
      } catch (e) {
        if (!cancelled) setFound({ words, rows: [], error: e.message });
      }
    }, 300);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [words, kind, repos.join()]);
  const rows = currentRows(found, words);
  const known = new Map(rows.map((r) => [ref(r), r]));
  const candidates = [...typed.map((r) => known.get(ref(r)) || r), ...rows.filter((r) => !typed.some((t) => ref(t) === ref(r)))]
    .filter((r) => !exclude.includes(ref(r)));
  const at = Math.min(active, Math.max(candidates.length - 1, 0));
  const close = () => { setText(""); setActive(0); };
  useOutside(box, Boolean(words), close);
  const pick = (item) => {
    if (!item) return;
    onPick(item);
    setActive(0);
    if (many) return;  // the words stay, so the list stays open for the next; exclude drops the one just picked
    setText("");
    if (box.current) box.current.querySelector("input").blur();
  };
  const optionId = (i) => `${id}-o${i}`;
  const open = Boolean(words);
  const why = found.error ? `Search failed: ${found.error}. A reference like ${repos.length === 1 ? "#12" : "hub#12"} still works.`
    : byRef ? (refs.outside.length ? `${refs.outside.join(", ")}: ${repos.length ? `not in ${repos.join(", ")}` : "name the repository, as repo#N"}.` : "Already chosen.")
    : words.length < 2 ? "Type a reference or a few words." : found.words === words ? "Nothing matches." : "Searching…";
  return html`<div class="picker" ref=${box} onfocusout=${open ? leaves(box, close) : undefined}>
    <input role="combobox" class="mono" aria-expanded=${open ? "true" : "false"} aria-controls=${`${id}-list`} aria-autocomplete="list"
      aria-activedescendant=${open && candidates.length ? optionId(at) : undefined} aria-label=${label}
      placeholder=${repos.length === 1 ? `#number or words in ${repos[0]}` : "repo#number or words"} value=${text}
      onInput=${(e) => { setText(e.target.value); setActive(0); }}
      onKeyDown=${(e) => listKeys(e, { size: candidates.length, active: at, setActive, pick: () => pick(candidates[at]), close, open })} />
    ${open && html`<div class="pop"><div role="listbox" id=${`${id}-list`} aria-label=${label}>
      ${candidates.map((c, i) => html`<div role="option" id=${optionId(i)} aria-selected=${i === at ? "true" : "false"} data-active=${i === at ? "" : undefined}
        onMouseDown=${(e) => e.preventDefault()} onClick=${() => pick(c)}><${ItemPill} ...${c} plain /></div>`)}
      ${!candidates.length && html`<p class="small soft" style="padding: 8px" role="status">${why}</p>`}
    </div></div>`}
  </div>`;
}

// --- overview ----------------------------------------------------------------------
const CI_KIND = { success: "pass", failure: "fail", error: "fail", pending: "run", expected: "run" };
const CI_WORD = { pass: "CI passing", fail: "CI failing", run: "CI running", open: "No CI" };

function Strip({ marks }) {
  if (!marks) return html`<span class="strip"></span>`;
  if (!marks.length) return html`<span class="small soft">No runs yet</span>`;
  const failed = marks.filter((m) => m === "fail").length;
  return html`<span class="strip" role="img" aria-label="${failed} of last ${marks.length} runs failed">
    ${marks.map((m) => html`<i class=${m}></i>`)}</span>`;
}

function RepoDetail({ repo, layer }) {
  const { data } = useLoad(() => api(`issues${params({ repo: repo.name })}`), [repo.name]);
  const labels = useMemo(() => {
    const counts = {};
    for (const issue of data || []) for (const l of issue.labels) counts[l.name] = (counts[l.name] || 0) + 1;
    return Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 6);
  }, [data]);
  const top = labels.length ? labels[0][1] : 1;
  return html`<section class="panel" aria-labelledby="h-detail">
    <div class="stack tight"><${Eyebrow} soft>${layer}<//>
      <h2 id="h-detail" class="mono" style="font-size: 21px; font-weight: 600; overflow-wrap: anywhere">GlassineOS/${repo.name}</h2>
      ${repo.description && html`<p class="small soft">${repo.description}</p>`}</div>
    <div class="minis">
      <div class="mini"><${Eyebrow} soft>Issues<//><b>${repo.issues}</b></div>
      <div class="mini"><${Eyebrow} soft>PRs<//><b>${repo.prs}</b></div>
      <div class="mini"><${Eyebrow} soft>Commits<//><b>${repo.commits == null ? "–" : repo.commits}</b></div>
    </div>
    <div class="stack tight">
      <h3 class="eyebrow">Open issues by label</h3>
      ${labels.map(([name, n]) => html`<div class="barrow"><span title=${name}>${name}</span>
        <span class="bar"><i style="width: ${Math.round(n / top * 100)}%"></i></span><span style="text-align: right">${n}</span></div>`)}
      ${data && !labels.length && html`<span class="small soft">No labelled open issues.</span>`}
    </div>
    <dl class="defs" style="border-top: 1px dotted var(--ink); padding-top: 14px">
      <dt>Last commit</dt><dd>${repo.head_title || "–"}${repo.head_date ? ` · ${ago(repo.head_date)}` : ""}</dd>
      <dt>Release</dt><dd class="mono">${repo.release || "none"}</dd>
    </dl>
    <div class="row">
      <button onClick=${() => launch({ action: "new-security-audit", repos: [repo.name], from: { view: "Overview" } })}>＋ Audit or plan…</button>
      <a class="button" href=${hash("work", { repo: repo.name })}>Issues & PRs</a>
      <a class="button primary" href=${hash("shells", { new: 1, name: repo.name })}>New shell</a>
      <a class="button" href=${repo.url} target="_blank" rel="noreferrer noopener">GitHub</a>
    </div>
  </section>`;
}

function NeedsYou({ data, sessions, ready }) {
  // No project scope yet just means no board rows here: the Roadmap page explains that.
  const board = useLoad(async () => {
    const [project, issues] = await Promise.all([api("project"), api("issues?repo=hub")]);
    if (!project.columns) return [];
    const on = new Set(project.columns.flatMap((c) => c.items.filter((i) => i.repo === "hub").map((i) => i.number)));
    return issues.filter((i) => !on.has(i.number));
  }, [], 300000);
  const rows = [];
  for (const s of sessions) {
    if (s.agent && s.agent.waiting) rows.push({ kind: "Waiting", cls: "mark", title: `${s.name} is waiting for you`, ref: whereFrom(s.agent), href: hash("shells", { name: s.name }) });
  }
  for (const g of data.groups) {
    for (const r of g.repos) {
      if (r.ci === "failure" || r.ci === "error") rows.push({ kind: "Failed", cls: "bad", title: `CI is failing on ${r.branch || "the default branch"}`, ref: r.name, href: hash("work", { tab: "actions", repo: r.name, status: "failure" }) });
    }
  }
  for (const p of ready) rows.push({ kind: "Merge", cls: "dim", title: `${p.title}: checks green`, ref: `${p.repo}#${p.number}`, href: hash("work", { tab: "prs", repo: p.repo, item: p.number }) });
  for (const i of board.data || []) rows.push({ kind: "Board", cls: "dim", title: `${i.title}: not on the roadmap`, ref: `hub#${i.number}`, href: hash("roadmap") });
  return html`<section aria-labelledby="h-attn" class="stack tight">
    <h2 id="h-attn" class="dotted" style="font-size: 21px; font-weight: 600">Needs you</h2>
    ${rows.map((a) => html`<a class="attn" href=${a.href}><span class="badge ${a.cls}">${a.kind}</span>
      <span class="t"><span style="font-weight: 500; line-height: 1.35">${a.title}</span>
        <span class="mono soft" style="font-size: 12.5px">${a.ref}</span></span></a>`)}
    ${!rows.length && html`<p class="small soft">Nothing right now.</p>`}
  </section>`;
}

// A discard that found more than a little that git ignores: it stays until you've seen what would go.
function DiscardIgnored({ item, onNo, onYes }) {
  return html`<${Confirm} title=${`Discard ${item.name} and its ignored files?`} danger label="Discard them too"
    text=${`Git ignores these, so they aren't on GitHub and can't come back: ${item.ignored.paths.join(", ")} (${bytes(item.ignored.size)}). Save what you need first, or the session stays as it is.`}
    onNo=${onNo} onYes=${onYes} />`;
}

function Workspace() {
  const { data, reload } = useLoad(() => api("workspace").catch(() => null), [], 60000);
  const [discarding, setDiscarding] = useState(null);
  const [ignoring, setIgnoring] = useState(null);
  if (!data) return null;
  const words = (c) => [c.dirty ? `${c.dirty} uncommitted` : "", c.unpushed ? `${c.unpushed} unpushed` : ""].filter(Boolean).join(", ");
  const off = data.main.filter((m) => m.dirty || m.unpushed || (m.default && m.branch !== m.default));
  return html`<section aria-labelledby="h-ws" class="stack tight">
    <h2 id="h-ws" class="dotted" style="font-size: 21px; font-weight: 600">Workspace</h2>
    <span class="mono soft" style="font-size: 12.5px; overflow-wrap: anywhere">${data.root}</span>
    <span class="small">Claude login: <span class="mono">${data.claude_login || "the default"}</span></span>
    <span class="small">${count(data.main.length, "main checkout")}${off.length ? `, ${off.length} not clean on its default branch` : ", all clean"}</span>
    ${off.map((m) => html`<div class="tool-row"><span class="mono" style="font-size: 13px">${m.repo}</span>
      <span class="small soft">${m.branch}${words(m) ? ` · ${words(m)}` : ""}</span></div>`)}
    ${data.tasks.map((t) => html`<div class="stack" style="gap: 2px; padding: 8px 0; border-top: 1px dotted var(--ink)">
      ${t.live ? html`<a class="mono" style="font-size: 13.5px; font-weight: 600" href=${hash("shells", { name: t.name })}>${t.name}</a>` : html`<span class="mono" style="font-size: 13.5px; font-weight: 600">${t.name}</span>`}
      ${t.checkouts.map((c) => html`<span class="small soft">${c.repo} · ${c.branch}${words(c) ? ` · ${words(c)}` : ""}</span>`)}
      ${t.session && !t.live && html`<span class="row" style="gap: 8px"><span class="small soft">Shell ended.</span><a class="small" href=${hash("shells")}>Resume under Sessions</a><button class="plain" onClick=${() => setDiscarding(t.name)}>Discard…</button></span>`}</div>`)}
    ${!data.tasks.length && html`<span class="small soft">No tasks open.</span>`}
    ${discarding && html`<${Confirm} title=${`Discard ${discarding}?`} danger label="Discard"
      text="Its shell has ended. Its worktree goes, with anything uncommitted in it. Commits stay on the branch."
      onNo=${() => setDiscarding(null)} onYes=${async () => {
        const name = discarding;
        const r = await api(`shells/${encodeURIComponent(name)}?discard=1`, { method: "DELETE" });
        setDiscarding(null);
        if (r && r.ignored) setIgnoring({ name, ignored: r.ignored });
        reload();
      }} />`}
    ${ignoring && html`<${DiscardIgnored} item=${ignoring} onNo=${() => setIgnoring(null)} onYes=${async () => {
        const name = ignoring.name;
        setIgnoring(null);
        await api(`shells/${encodeURIComponent(name)}?discard=1&drop_ignored=1`, { method: "DELETE" });
        reload();
      }} />`}
  </section>`;
}

function RepoCopies() {
  const { data } = useLoad(() => api("repo-copies").catch(() => null), [], 300000);
  if (!data) return null;
  const failed = data.repos.filter((r) => r.refresh_failed);
  const missing = data.repos.filter((r) => !r.copied && !r.refresh_failed);
  return html`<section aria-labelledby="h-copies" class="stack tight">
    <h2 id="h-copies" class="dotted" style="font-size: 21px; font-weight: 600">Repository copies</h2>
    <span class="small">${data.repos.length === 1 ? "1 repository" : `${data.repos.length} repositories`}${failed.length ? `, ${failed.length} not refreshed` : ""}${missing.length ? `, ${missing.length} not copied yet` : ""}</span>
    ${data.list_error && html`<span class="small"><b>Couldn't list the organization's repositories:</b> ${data.list_error}. Last list: ${data.listed || "none"}.</span>`}
    ${failed.map((r) => html`<div class="tool-row"><span class="mono" style="font-size: 13px">${r.repo}</span>
      <span class="small"><b>Refresh failed</b> ${r.refresh_failed}${r.refreshed ? ` Last refreshed ${r.refreshed}.` : ""}</span></div>`)}
    ${data.maps && html`<span class="small">Code map: ${data.maps.mapped === 1 ? "1 repository" : `${data.maps.mapped} repositories`} mapped${data.maps.forks.length ? `, forks left out (${data.maps.forks.join(", ")})` : ""}${data.maps.failed.length ? `, ${data.maps.failed.length} failed` : ""}</span>`}
    ${data.maps && data.maps.failed.map((m) => html`<div class="tool-row"><span class="mono" style="font-size: 13px">${m.repo}</span>
      <span class="small"><b>Map not built</b> ${m.tried}: ${m.error}. Any earlier map stands.</span></div>`)}
    ${data.held.length > 0 && html`<span class="small soft">Sessions keep ${count(data.held.length, "snapshot")}, each holding on to old data as the copies move on, until the session is removed:</span>`}
    ${data.held.map((h) => html`<div class="tool-row"><span class="mono" style="font-size: 13px">${h.session}</span>
      <span class="small soft">${h.copy}</span></div>`)}
  </section>`;
}

function DocsStat() {
  const { data, error } = useLoad(() => api("docs/status"), [], 120000);
  return html`<a class="stat" href=${hash("knowledge")}><${Eyebrow} soft>Docs index<//>
    <b>${error ? "unknown" : data ? data.state : "…"}</b>
    <span class="small soft">${data ? `site ${data.published.slice(0, 7)} · head ${data.head.slice(0, 7)}` : error || " "}</span></a>`;
}

function Overview({ asks }) {
  const { data, error } = useLoad(() => api("overview"), [], 60000);
  const strips = useLoad(() => api("overview/runs"), [], 300000);
  const prs = useLoad(() => api("prs"), [], 300000);
  const ready = (prs.data || []).filter((p) => p.checks === "passing" && !p.isDraft);
  const sessions = useSessions();
  const [picked, setPicked] = useState(null);
  const list = sessions.data || [];
  if (!data) return html`<main class="page"><h1>Overview</h1><${Err} text=${error} />${!error && html`<p class="soft">Loading…</p>`}</main>`;
  const placed = data.groups.filter((g) => g.key !== "unplaced");
  const unplaced = data.groups.find((g) => g.key === "unplaced");
  const every = data.groups.flatMap((g) => g.repos.map((r) => ({ ...r, layer: g.title })));
  const current = every.find((r) => r.name === picked) || every.find((r) => r.ci === "failure") || every[0];
  const failing = every.filter((r) => r.ci === "failure" || r.ci === "error");
  const waiting = list.filter((s) => s.agent && s.agent.waiting).length;
  return html`<main class="page">
    <div class="row" style="justify-content: space-between; align-items: flex-end; gap: 12px 24px">
      <div class="stack tight"><${Eyebrow} soft>GlassineOS org · ${data.totals.repos} repositories · ${placed.length} layers<//><h1>Overview</h1></div>
</div>
    <${Err} text=${error} />
    <section class="stats" aria-label="Org totals">
      <a class="stat" href=${hash("work", { tab: "issues" })}><${Eyebrow} soft>Open issues<//><b>${data.totals.issues}</b><span class="small soft">across ${data.totals.repos} repositories</span></a>
      <a class="stat" href=${hash("work", { tab: "prs" })}><${Eyebrow} soft>Open PRs<//><b>${data.totals.prs}</b><span class="small soft">${ready.length} ready to merge</span></a>
      <a class="stat" href=${hash("work", { tab: "actions", status: "failure" })}><${Eyebrow} soft>CI<//><b>${failing.length ? `${failing.length} failing` : "passing"}</b><span class="small soft">${failing.map((r) => r.name).join(", ") || "on the default branches"}</span></a>
      <${DocsStat} />
      <a class="stat" href=${hash("shells")}><${Eyebrow} soft>Sessions<//><b>${list.length}</b><span class="small soft">${waiting ? `${waiting} waiting for you` : "none waiting"}</span></a>
    </section>
    <${ApiBudget} />
    <div class="columns">
      <section class="wide stack" style="gap: 24px" aria-labelledby="h-layers">
        <div class="row dotted"><h2 id="h-layers" class="grow" style="font-size: 27px; line-height: 1.2; font-weight: 600">Repositories by layer</h2>
          <span class="small soft">Layers from <code>config/repos.toml</code></span></div>
        ${placed.map((g, i) => html`<div class="layer">
          <div class="name" title=${g.summary}><span class="num" aria-hidden="true">${i + 1}</span><h3>${g.title}</h3></div>
          <div class="repos">${g.repos.map((r) => {
            const kind = CI_KIND[r.ci] || "open";
            return html`<button type="button" class="repo keycap" aria-pressed=${current && current.name === r.name ? "true" : "false"} onClick=${() => setPicked(r.name)}>
              <span class="title"><${StateIcon} kind=${kind} label=${CI_WORD[kind]} /><span class="grow">${r.name}</span></span>
              <span class="mono" style="font-size: 12.5px">${count(r.issues, "issue")} · ${r.prs} PR${r.prs === 1 ? "" : "s"}</span>
              <${Strip} marks=${strips.data ? strips.data[r.name] : null} />
              <span class="soft" style="font-size: 12.5px">${r.head_date ? ago(r.head_date) : "no commits"} · ${r.release || "no release"}</span>
            </button>`;
          })}</div></div>`)}
        ${unplaced && html`<div class="unplaced"><span class="eyebrow" style="flex: 0 0 170px">Unplaced · ${unplaced.repos.length}</span>
          <span class="mono" style="font-weight: 600">${unplaced.repos.map((r) => r.name).join(", ")}</span>
          <span class="small soft" style="flex: 1 1 240px">In the org but not in <code>config/repos.toml</code>. Add to a layer there.</span></div>`}
        <p class="small soft">Run strip: last 10 workflow runs on the default branch, oldest first. Outlined: passed · filled: failed · dashed: running.</p>
      </section>
      <aside class="aside stack" style="gap: 24px">
        ${current && html`<${RepoDetail} key=${current.name} repo=${current} layer=${current.layer} />`}
        <${DeviceCard} asks=${asks} />
        <${NeedsYou} data=${data} sessions=${list} ready=${ready} />
        <${Workspace} />
        <${RepoCopies} />
      </aside>
    </div>
  </main>`;
}

// --- roadmap ------------------------------------------------------------------------
function AddToBoard({ onDone, onCancel }) {
  const [repo, setRepo] = useState("hub");
  const [number, setNumber] = useState("");
  const act = useAct(onDone);
  return html`<div class="notice quiet"><span>Add an existing issue or pull request of the org.</span>
    <label class="field"><span>Repository</span><input value=${repo} onInput=${(e) => setRepo(e.target.value)} /></label>
    <label class="field"><span>Number</span><input inputmode="numeric" value=${number} onInput=${(e) => setNumber(e.target.value)} /></label>
    <button class="primary" disabled=${act.busy || !repo || !number} onClick=${() => act.run(() => post("project/add", { repo, number }))}>Add</button>
    <button onClick=${onCancel}>Cancel</button><${Err} text=${act.error} /></div>`;
}

function Roadmap() {
  const { data, error, reload } = useLoad(() => api("project"), [], 120000);
  const hubIssues = useLoad(() => api("issues?repo=hub"), []);
  const [adding, setAdding] = useState(false);
  const act = useAct(async () => { await reload(); await hubIssues.reload(); });
  const title = html`<div class="stack tight" style="max-width: 68ch"><${Eyebrow} soft>Org project · ${data && data.title ? data.title : "GlassineOS roadmap"}<//>
    <h1>Roadmap</h1>
    <p class="soft" style="font-size: 17px; line-height: 1.65">Strategic issues live in GlassineOS/hub. Each card rolls up its sub-issues from the repositories that do the work.</p></div>`;
  if (data && data.needs_scope) {
    return html`<main class="page close">${title}<div class="notice"><span>The host's GitHub login can't see Projects yet. Run this on the host, then reload:</span><pre class="mono">${data.command}</pre></div></main>`;
  }
  if (data && data.missing) {
    return html`<main class="page close">${title}<div class="notice"><span>The organization has no open project called “${data.title}”. Create it once on the host:</span><pre class="mono">gh project create --owner GlassineOS --title "${data.title}"</pre></div></main>`;
  }
  const columns = data ? data.columns.filter((c) => c.id) : [];
  const onBoard = new Set(data ? data.columns.flatMap((c) => c.items.filter((i) => i.repo === "hub").map((i) => i.number)) : []);
  const orphans = data && hubIssues.data ? hubIssues.data.filter((i) => !onBoard.has(i.number)) : [];
  const move = (item, option) => act.run(() => post("project/move", { project: data.id, item: item.id, field: data.status_field, option }));
  return html`<main class="page close">
    <div class="row" style="align-items: flex-end; justify-content: space-between">${title}
      <div class="row">
        <button onClick=${() => launch({ action: "new-roadmap-item", repos: ["hub"], from: { view: "Roadmap" } })}>＋ Roadmap item</button>
        <button onClick=${() => setAdding(true)}>Add existing issue</button>
        <a class="button primary" href=${hash("work", { tab: "issues", repo: "hub", new: 1, roadmap: 1 })}>New strategic issue</a>
      </div></div>
    <${Err} text=${error || act.error} />
    ${adding && html`<${AddToBoard} onCancel=${() => setAdding(false)} onDone=${async () => { setAdding(false); await reload(); }} />`}
    ${orphans.length > 0 && html`<div class="notice"><span>Strategic issues in hub that aren't on the board yet:</span>
      ${orphans.slice(0, 6).map((o) => html`<button class="plain" disabled=${act.busy} onClick=${() => act.run(() => post("project/add", { repo: "hub", number: o.number }))}>Add <span class="mono">hub#${o.number}</span> · ${o.title}</button>`)}</div>`}
    ${!data && !error && html`<p class="soft">Loading…</p>`}
    ${data && html`<div class="board">${data.columns.map((col) => {
      const index = columns.findIndex((c) => c.id === col.id);
      return html`<section class="column" aria-label=${col.name}>
        <header class="dotted"><h2 class="eyebrow">${col.name}</h2><span class="mono" style="font-size: 13px; font-weight: 600">${col.items.length}</span></header>
        ${col.items.map((item) => {
          const done = item.sub_issues.reduce((n, s) => n + s.done, 0);
          const total = item.sub_issues.reduce((n, s) => n + s.total, 0);
          const pct = total ? Math.round(done / total * 100) : 0;
          const left = index > 0 ? columns[index - 1] : null;
          const right = index >= 0 ? columns[index + 1] : columns[0];
          return html`<article class="card keycap">
            <div class="row" style="justify-content: space-between; align-items: flex-start; flex-wrap: nowrap">
              <a class="title" href=${item.repo ? hash("work", { tab: item.kind === "PullRequest" ? "prs" : "issues", repo: item.repo, item: item.number }) : data.url}>${item.title}</a>
              ${item.repo && html`<span class="ref">${item.repo}#${item.number}</span>`}</div>
            ${total > 0 && html`<div class="row" style="flex-wrap: nowrap">
              <span class="bar grow" role="progressbar" aria-label="Sub-issues closed" aria-valuenow=${pct} aria-valuemin="0" aria-valuemax="100" style="height: 8px"><i style="width: ${pct}%"></i></span>
              <span class="mono" style="font-size: 12.5px; font-weight: 600">${done}/${total}</span></div>
              <div class="row" style="gap: 6px">${item.sub_issues.map((s) => html`<span class="chip">${s.repo} ${s.done}/${s.total}</span>`)}</div>`}
            <div class="row small soft" style="flex-wrap: nowrap">
              <span class="grow">${item.assignees.join(", ") || "unassigned"}</span>
              <button class="icon" aria-label="Move left${left ? ` to ${left.name}` : ""}" disabled=${act.busy || !left} onClick=${() => move(item, left.id)}><${Chevron} /></button>
              <button class="icon" aria-label="Move right${right ? ` to ${right.name}` : ""}" disabled=${act.busy || !right} onClick=${() => move(item, right.id)}><${Chevron} right /></button>
            </div></article>`;
        })}</section>`;
    })}</div>
    <p class="small soft">Arrows move a card one status column. Sub-issue counts are closed / total.</p>`}
  </main>`;
}

// --- Launch: notes and pins for the planner ------------------------------------------------
const STEER_CHIPS = {
  pr: ["error paths first", "keep the diff small", "check it against the docs", "add tests"],
  issue: ["only propose, don't apply", "look for duplicates", "keep the change small"],
  run: ["compare with earlier runs", "don't touch the runner image"],
};
const PIN_WORDS = { thread: "Review thread", ref: "Issue / PR", file: "Repo file", docs: "Docs page", url: "Link", text: "Text snippet" };
const PIN_HINTS = { ref: "hub#44", file: "kernel:drivers/gpu/drm/epd/epd_lut.c", docs: "docs path", text: "Something the agent should know" };
const pinKind = (v) => (/^https?:/.test(v) ? "url" : /#\d/.test(v) ? "ref" : v.indexOf(":") > 0 ? "file" : "docs");

function SteerFields({ kind, notes, pins, onNotes, onPins }) {
  const [typed, setTyped] = useState("");
  const [forced, setForced] = useState(null);
  const add = () => {
    const label = typed.trim();
    if (!label || pins.some((p) => p.label === label)) return;
    onPins([...pins, { kind: forced || pinKind(label), label }]);
    setTyped(""); setForced(null);
  };
  return html`<div class="stack" style="gap: 8px">
    <label class="field"><span>Notes for the planner</span>
      <textarea rows="2" maxlength="4000" placeholder="What matters most here" value=${notes} onInput=${(e) => onNotes(e.target.value)}></textarea></label>
    <div class="row" style="gap: 6px"><span class="small soft">Add:</span>
      ${(STEER_CHIPS[kind] || []).map((t) => html`<button class="pill" onClick=${() => onNotes(notes.trim() ? `${notes.trim()}; ${t}` : t)}>+ ${t}</button>`)}</div>
    <${Eyebrow}>Pinned context · ${pins.length || "none yet"}<//>
    ${pins.length > 0 && html`<ul class="row" style="gap: 6px">${pins.map((p) => html`<li class="label"><span class="soft">${PIN_WORDS[p.kind]}</span> ${p.label}
      <button aria-label="Remove ${p.label}" onClick=${() => onPins(pins.filter((x) => x !== p))}>
        <svg width="12" height="12" viewBox="0 0 12 12" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M3 3l6 6M9 3l-6 6" /></svg></button></li>`)}</ul>`}
    <form class="row" style="gap: 6px" onSubmit=${(e) => { e.preventDefault(); add(); }}>
      <input aria-label="Reference to pin" maxlength="1000" class="mono grow" style="font-size: 13px" placeholder=${forced ? PIN_HINTS[forced] : "hub#44, kernel:path/to/file, a docs path or a link"} value=${typed} onInput=${(e) => setTyped(e.target.value)} />
      <button disabled=${!typed.trim()}>Pin</button></form>
    <div class="row" style="gap: 6px" role="group" aria-label="What you're pinning"><span class="small soft">Pin as:</span>
      ${["ref", "file", "docs", "text"].map((k) => html`<button class="pill" aria-pressed=${forced === k ? "true" : "false"} onClick=${() => setForced(forced === k ? null : k)}>${PIN_WORDS[k]}</button>`)}</div>
  </div>`;
}

// 006 FR-015, as Launch needs it: the item's agent actions, each opening Launch on this item (006/PR 1 adds the rest of the row).
// The kind's agent actions that apply to the item now: `when` by its checks, `needs: "review"` only with something to address.
function offeredFor(actions, facts) {
  return (actions || []).filter((a) => (!a.when || a.when === (facts.failing ? "failing" : "not-failing"))
    && (!a.needs || (a.needs === "review" && facts.openThreads + facts.reviews > 0)));
}

// 006 FR-007: the one action that fits the item best. Fix if failing, address if a review asked for changes, triage if
// nobody has labelled it, else review a PR, implement an issue, investigate a run. Work's rows use it too.
const BEST_VERB = { pr: "review", issue: "implement", run: "investigate" };
function bestAction(kind, facts, offered) {
  const verb = facts.failing ? (kind === "run" ? "investigate" : "fix")
    : kind === "pr" && (facts.changesRequested || facts.openThreads > 0) ? "address"
    : kind === "issue" && facts.untriaged ? "triage" : BEST_VERB[kind];
  return offered.find((a) => a.verb === verb) || offered.find((a) => a.verb) || offered[0] || null;
}

const useKindActions = (kind) => useLoad(() => api(`agents/actions${params({ object: kind })}`), [kind]);

// 006 FR-015: the kind's agent actions as blue buttons, the best one filled, and "New work from this…". Each opens Launch on the item.
function LaunchRow({ kind, repo, number, facts }) {
  const { data, error } = useKindActions(kind);
  const offered = offeredFor(data, facts);
  const best = bestAction(kind, facts, offered);
  const ordered = best ? [best, ...offered.filter((a) => a !== best)] : offered;
  const pins = facts.threadPins || [];
  const titleOf = (a) => (a.needs === "review" ? `${a.title} · ${pins.length ? count(pins.length, "ticked thread") : facts.openThreads === 1 ? "1 open thread" : facts.openThreads ? `all ${facts.openThreads} threads` : count(facts.reviews, "review")}` : a.title);
  const here = `${repo}#${number}`;
  const open = (a) => launch({ action: a.id, covers: [{ kind, repo, number }], pins: a.needs === "review" ? pins : [], from: { view: "Work", ref: here } });
  return html`<section class="spawn keycap" aria-labelledby="h-launch">
    <div class="row" style="gap: 4px 12px; align-items: baseline"><h2 id="h-launch" class="row" style="gap: 8px; font-size: 19px; font-weight: 600"><${TermIcon} />Launch on ${here}</h2>
      <span class="small soft">Each opens Launch on this item: a planner reads first, and nothing runs until you've read its plan.</span></div>
    <${Err} text=${error} />
    <div class="row">${ordered.map((a) => html`<button class=${a === best ? "primary" : "pen"} title=${`${a.summary} ${a.ceiling}`} onClick=${() => open(a)}><${TermIcon} />${titleOf(a)}</button>`)}
      <button class="pen" onClick=${() => launch({ repos: [repo], context: here, pins: [{ kind: "ref", label: here }], from: { view: "Work", ref: here } })}>＋ New work from this…</button></div>
  </section>`;
}

// 006 FR-025: no session covers the item, so the best action is offered as a suggestion, in Needs you's card style.
function SuggestBest({ kind, repo, number, facts }) {
  const { data } = useKindActions(kind);
  const best = bestAction(kind, facts, offeredFor(data, facts));
  if (!best) return html`<p class="small soft">No session on this item.</p>`;
  const here = `${repo}#${number}`;
  return html`<article class="ask calm compact"><div class="ask-head"><span class="ask-kind">SESSION · SUGGESTED</span></div>
    <div class="ask-body"><h3 class="ask-title">${best.title} ${here}</h3><p class="small">${best.summary}</p>
      <p class="small soft">A planner reads this first. Nothing runs until you've read its plan.</p>
      <div class="row"><button class="primary" onClick=${() => launch({ action: best.id, covers: [{ kind, repo, number }], pins: best.needs === "review" ? facts.threadPins || [] : [], from: { view: "Work", ref: here } })}><${TermIcon} />Launch…</button></div></div></article>`;
}

// 006 FR-023–FR-025: every session on the item. Embedded ones as persona tabs, each its SessionView; the ones in the
// background as links; none, a suggestion for the best action.
function SessionsOn({ kind, repo, number, facts, sessions, phaseOf, place, setPhase, asks, onReload }) {
  const here = `${repo}#${number}`;
  const embedded = sessions.filter((s) => phaseOf(s) === "embedded");
  const behind = sessions.filter((s) => phaseOf(s) !== "embedded");
  const [tab, setTab] = useState(null);
  const current = embedded.find((s) => s.name === tab) || embedded[0];
  return html`<section class="stack" aria-labelledby="h-sessions-on" style="gap: 10px">
    <h2 id="h-sessions-on" style="font-size: 19px; font-weight: 600">Sessions on ${here} · ${sessions.length}</h2>
    ${!sessions.length && html`<${SuggestBest} kind=${kind} repo=${repo} number=${number} facts=${facts} />`}
    ${embedded.length > 0 && html`<div role="tablist" aria-label="Sessions on ${here}" class="tabs">${embedded.map((s) => html`<button role="tab" aria-selected=${s === current ? "true" : "false"} onClick=${() => setTab(s.name)}>
        <${PersonaBadge} persona=${personaOf(s.agent)} hidden /> ${s.agent.persona_name || s.agent.persona} <span class="mono soft" style="font-size: 12.5px">${s.name}</span></button>`)}</div>
      <${SessionView} key=${current.name} session=${current} mode="embedded" asks=${asks} here=${here}
        onView=${(m) => setPhase(current.name, m)} onEnded=${onReload} onGone=${onReload} />`}
    ${behind.length > 0 && html`<div role="status" class="notice quiet"><span class="grow">${behind.length} sent to background: ${behind.map((s, i) => html`${i ? ", " : ""}<a class="mono" href=${hash("shells", { name: s.name })}>${s.name}</a> (${s.agent.persona_name || s.agent.persona}${s.agent.waiting ? ", waiting" : ""})`)}</span>
      ${behind.map((s) => html`<button class="plain" onClick=${() => place(s.name, "embedded")}>Bring back ${behind.length > 1 ? s.name : ""}</button>`)}</div>`}
  </section>`;
}

// The host's user, for "On GitHub, as …": the page's GitHub actions run on the host's own gh. Set by Hub.
let HOST_USER = "";

// --- work item: GitHub actions, as you -------------------------------------------------------
// Which labels the item has, and the repository's, ticked on and off. One call adds and removes.
function LabelsDialog({ repo, have, path, onDone, onNo }) {
  const ref = useRef();
  const all = useLoad(() => api(`labels/${repo}`), [repo]);
  const [on, setOn] = useState(() => new Set(have));
  const act = useAct();
  useEffect(() => { ref.current.showModal(); }, []);
  const names = [...new Set([...(all.data || []).map((l) => l.name), ...have])].sort((a, b) => a.localeCompare(b));
  const add = names.filter((n) => on.has(n) && !have.includes(n));
  const remove = have.filter((n) => !on.has(n));
  const apply = () => act.run(async () => { await post(path, { add, remove }); onDone(`Labels changed${add.length ? `: +${add.join(", +")}` : ""}${remove.length ? `${add.length ? "," : ":"} −${remove.join(", −")}` : ""}`); });
  return html`<dialog ref=${ref} onClose=${onNo}><h2>Labels</h2>
    <${Err} text=${all.error || act.error} />${!all.data && !all.error && html`<p class="soft">Loading…</p>`}
    <div class="stack" style="gap: 4px; max-height: 50vh; overflow: auto">${names.map((n) => html`<label class="row" style="gap: 8px"><input type="checkbox" checked=${on.has(n)}
      onChange=${() => setOn((s) => { const x = new Set(s); if (!x.delete(n)) x.add(n); return x; })} />${n}</label>`)}</div>
    <div class="row"><button class="gh" disabled=${act.busy || !(add.length || remove.length)} onClick=${apply}>Apply</button><button onClick=${onNo}>Cancel</button></div></dialog>`;
}

function MergeDialog({ data, onYes, onNo }) {
  const ref = useRef();
  const [method, setMethod] = useState("squash");
  useEffect(() => { ref.current.showModal(); }, []);
  return html`<dialog ref=${ref} onClose=${onNo}><h2>Merge this pull request?</h2>
    <p>${data.repo}#${data.number} at <span class="mono">${(data.headRefOid || "").slice(0, 12)}</span> into ${data.baseRefName}. Checks: ${data.checks}. If it has moved on from that commit, the merge fails.</p>
    <label class="field"><span>How</span><select value=${method} onChange=${(e) => setMethod(e.target.value)}>
      <option value="squash">Squash and merge</option><option value="merge">Merge commit</option><option value="rebase">Rebase and merge</option></select></label>
    <div class="row"><button class="gh" onClick=${() => onYes(method)}>Merge</button><button onClick=${onNo}>Cancel</button></div></dialog>`;
}

// Everything the black button offers for one kind (006 FR-030, FR-032, FR-033). Each entry says why it's off, or null.
function ghEntries({ kind, data, repo, number, base, behind }) {
  const page = { label: "Open on GitHub", disabled: null, href: data.url };
  if (kind === "pr") {
    const open = data.state === "OPEN";
    const merged = data.state === "MERGED";
    const blockers = (data.merge_blockers || []).map((b) => b.why);
    return [
      { id: "merge", label: "Merge…", done: "Merged", merge: true,
        disabled: merged ? "already merged" : !open ? "closed" : data.isDraft ? "a draft: mark it ready first" : blockers.length ? `off while ${blockers.join(", ")}` : null },
      { id: "ready", label: "Mark ready", done: "Marked ready", run: () => post(`${base}/ready`), disabled: !open ? "not open" : data.isDraft ? null : "not a draft" },
      { id: "update", label: behind ? `Update branch · ${behind} behind` : "Update branch", done: "Branch updated", run: () => post(`${base}/update-branch`),
        disabled: !open ? "not open" : behind === 0 ? `0 behind ${data.baseRefName}` : null },
      { id: "labels", label: "Labels…", labels: `${base}/labels`, disabled: null },
      open ? { id: "close", label: "Close", done: "Closed", run: () => post(`${base}/close`), disabled: null,
        confirm: { title: "Close without merging?", text: `${repo}#${number}: ${data.title}`, label: "Close pull request" } }
        : { id: "reopen", label: "Reopen", done: "Reopened", run: () => post(`${base}/reopen`), disabled: merged ? "merged pull requests can't reopen" : null },
      page,
    ];
  }
  if (kind === "issue") {
    const open = data.state === "OPEN";
    const mine = (data.assignees || []).some((a) => a.login === HOST_USER);
    const close = (reason, label) => ({ id: `close-${reason}`, label, done: `Closed as ${reason}`, run: () => post(`${base}/close`, { reason }),
      disabled: open ? null : "already closed", confirm: { title: `${label}?`, text: `${repo}#${number}: ${data.title}`, label } });
    return [
      close("completed", "Close as completed"),
      close("not planned", "Close as not planned"),
      { id: "reopen", label: "Reopen", done: "Reopened", run: () => post(`${base}/reopen`), disabled: open ? "it's open" : null },
      { id: "labels", label: "Labels…", labels: `${base}/labels`, disabled: null },
      { id: "assign", label: "Assign to me", done: "Assigned", run: () => post(`${base}/assign-me`), disabled: mine ? "assigned to you" : null },
      page,
    ];
  }
  const running = data.status !== "completed";
  return [
    { id: "rerun-failed", label: "Re-run failed jobs", done: "Re-run started", run: () => post(`${base}/rerun`, { failed_only: true }),
      disabled: running ? "running" : data.conclusion === "failure" ? null : "no job failed" },
    { id: "rerun-all", label: "Re-run all", done: "Re-run started", run: () => post(`${base}/rerun`, { failed_only: false }), disabled: running ? "running" : null },
    { id: "cancel", label: "Cancel run", done: "Cancelled", run: () => post(`${base}/cancel`), disabled: running ? null : "completed",
      confirm: { title: "Cancel this run?", text: `${data.workflowName} · ${data.displayTitle}`, label: "Cancel run" } },
    { id: "log", label: "Download full log", download: `${base}/log?all=1`, disabled: null },
    page,
  ];
}

// 006 FR-026–FR-029, FR-038: a black split button, as you on GitHub. Its main action is the first one that's on; the arrow
// opens the rest, the ones that are off saying why. Black, never blue: blue starts an agent (001 FR-013).
function GhActions({ kind, data, repo, number, base, behind, onDone }) {
  const entries = ghEntries({ kind, data, repo, number, base, behind });
  const main = entries.find((e) => !e.disabled && !e.href) || entries.find((e) => !e.href) || entries[0];
  const [menu, setMenu] = useState(false);
  const [modal, setModal] = useState(null);
  const [said, setSaid] = useState("");
  const [confirm, dialog] = useConfirm();
  const act = useAct();
  const box = useRef();
  useEffect(() => {
    if (!menu) return undefined;
    const away = (e) => { if (box.current && !box.current.contains(e.target)) setMenu(false); };
    const esc = (e) => { if (e.key === "Escape") setMenu(false); };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("pointerdown", away); document.removeEventListener("keydown", esc); };
  }, [menu]);
  // The view reloads at once and again after a few seconds, as GitHub can take a moment to show the change (FR-038).
  const finish = async (words) => { setSaid(`${words} by ${HOST_USER || "you"}.`); await onDone(); setTimeout(onDone, 4000); };
  const go = (e) => {
    setMenu(false);
    if (e.disabled) return;
    if (e.href) { window.open(e.href, "_blank", "noopener,noreferrer"); return; }
    if (e.merge) { setModal("merge"); return; }
    if (e.labels) { setModal("labels"); return; }
    if (e.download) {
      act.run(async () => {
        const text = await api(e.download);
        const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(new Blob([text], { type: "text/plain" })), download: `${repo}-run-${number}.log` });
        a.click();
        URL.revokeObjectURL(a.href);
      });
      return;
    }
    const doIt = () => act.run(async () => { await e.run(); await finish(e.done); });
    if (e.confirm) confirm({ ...e.confirm, danger: true }, doIt); else doIt();
  };
  const merge = (method) => { setModal(null); act.run(async () => { await post(`${base}/merge`, { method, head: data.headRefOid }); await finish("Merged"); }); };
  const have = (data.labels || []).map((l) => l.name);
  return html`<div class="ghactions" ref=${box}>${dialog}
    ${modal === "merge" && html`<${MergeDialog} data=${{ ...data, repo, number }} onYes=${merge} onNo=${() => setModal(null)} />`}
    ${modal === "labels" && html`<${LabelsDialog} repo=${repo} have=${have} path=${`${base}/labels`} onNo=${() => setModal(null)} onDone=${(w) => { setModal(null); finish(w); }} />`}
    <div class="ghsplit"><button class="gh" disabled=${act.busy || Boolean(main.disabled)} title=${main.disabled || ""} onClick=${() => go(main)}>${main.label}</button>
      <button class="gh arrow" aria-haspopup="menu" aria-expanded=${menu ? "true" : "false"} aria-label="More actions on GitHub" disabled=${act.busy} onClick=${() => setMenu(!menu)}>
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M3 5l4 4 4-4" /></svg></button></div>
    <span class="small soft">On GitHub, as <span class="mono">${HOST_USER || "the host's gh"}</span></span>
    ${menu && html`<ul role="menu" class="ghmenu" aria-label="Actions on GitHub">${entries.map((e) => html`<li role="none">
      <button role="menuitem" aria-disabled=${e.disabled ? "true" : "false"} onClick=${() => go(e)}><span>${e.label}</span>${e.disabled && html`<span class="why">${e.disabled}</span>`}</button></li>`)}</ul>`}
    <${Err} text=${act.error} />${said && html`<span role="status" class="small">${said}</span>`}</div>`;
}

// --- work item ---------------------------------------------------------------------------------
function Comments({ list }) {
  return list.map((c) => html`<article class="body">
    <span class="row small soft" style="gap: 8px"><span class="mono" style="font-size: 12.5px">${c.author && c.author.login} · ${ago(c.createdAt || c.submittedAt)}</span>
      ${c.badge && html`<span class="badge dim">${c.badge}</span>`}</span><${Md} text=${c.body} /></article>`);
}

const WORK_TAB = { issue: "issues", pr: "prs", run: "actions" };

// One item on its own page (006 FR-011–FR-014): where it is, its state, title and reference, the black GitHub button beside
// the title, a Details flyout, one line of facts; then Launch, the sessions on it, and its content.
function ItemFrame({ kind, repo, refText, title, state, stateCls, gh, details, facts, chips, launchRow, sessions, sections }) {
  const [tab, setTab] = useState(sections[0].id);
  const [showDetails, setShowDetails] = useState(false);
  const current = sections.find((x) => x.id === tab) || sections[0];
  return html`<div class="stack" style="gap: 10px">
      <nav aria-label="Breadcrumb" class="small mono crumbline"><a href=${hash("work", { tab: WORK_TAB[kind] })}>Work</a> › <a href=${hash("work", { tab: WORK_TAB[kind], repo })}>${repo}</a> › <span aria-current="page">${refText}</span></nav>
      <div class="itemhead"><div class="stack grow" style="gap: 6px">
          <h1 class="itemtitle">${title}</h1>
          <div class="row small soft" style="gap: 6px 12px"><span class="badge ${stateCls}">${state}</span><span class="mono">${refText}</span>
            <button class="link" aria-haspopup="dialog" onClick=${() => setShowDetails(true)}>Details</button></div></div>
        ${gh}</div>
      <p class="small facts">${facts.filter(Boolean).join(" · ")}</p>
      ${chips}</div>
    ${showDetails && html`<${DetailsFlyout} title=${`${refText} details`} onClose=${() => setShowDetails(false)}>${details}<//>`}
    ${launchRow}
    ${sessions}
    <section class="stack" aria-label="Content" style="gap: 16px">
      ${sections.length > 1 && html`<div role="tablist" aria-label="Item sections" class="tabs">${sections.map((x) => html`<button role="tab" aria-selected=${current.id === x.id ? "true" : "false"} onClick=${() => setTab(x.id)}>${x.label}</button>`)}</div>`}
      ${current.body}</section>`;
}

function DetailsFlyout({ title, onClose, children }) {
  const ref = useRef();
  useEffect(() => { ref.current.showModal(); }, []);
  return html`<dialog class="flyout" ref=${ref} onClose=${onClose} aria-label=${title}>
    <div class="row" style="justify-content: space-between"><h2>Details</h2><button class="plain" onClick=${() => ref.current.close()}>Close</button></div>
    ${children}</dialog>`;
}

// The checks as chips (006 FR-016): failing first, each linking to its run.
function CheckChips({ checks }) {
  if (!checks.length) return null;
  const order = (c) => ({ bad: 0, dim: 1, "": 2 }[CHECK_BADGE(c.state)[1]]);
  return html`<div class="row" style="gap: 6px" aria-label="Checks">${[...checks].sort((a, b) => order(a) - order(b)).map((c) => {
    const [word, cls] = CHECK_BADGE(c.state);
    const name = c.workflow && c.workflow !== c.name ? `${c.workflow} · ${c.name}` : c.name;
    return c.url ? html`<a class="checkchip ${cls}" href=${c.url} target="_blank" rel="noreferrer noopener">${word} · ${name}</a>` : html`<span class="checkchip ${cls}">${word} · ${name}</span>`;
  })}</div>`;
}

function Comment({ busy, onSend, object, repo, number, onDraft }) {
  const [text, setText] = useState("");
  const [note, setNote] = useState("");
  const draft = useAct();
  const ask = (kind) => draft.run(async () => {
    setNote("Drafting with claude -p, read-only…");
    try {
      const r = await post("agents/draft", { kind, object, repo, number });
      setText((t) => (t.trim() ? `${t.trim()}\n\n${r.text}` : r.text));
      setNote("Draft ready. Edit it, then Post: nothing is posted until you do.");
    } catch (e) { setNote(""); throw e; }
  });
  return html`<label class="field" style="gap: 6px"><span>Comment</span>
    <textarea rows="4" placeholder="Markdown supported" value=${text} onInput=${(e) => setText(e.target.value)}></textarea></label>
    <${Err} text=${draft.error} />
    <div class="row"><button class="gh" disabled=${busy || !text.trim()} onClick=${async () => { await onSend(text); setText(""); setNote(""); }}>Post</button>
      ${onDraft ? html`<button class="pen" onClick=${() => onDraft(text)}><${TermIcon} />Draft with Claude</button>`
        : html`<button class="pen" disabled=${draft.busy} onClick=${() => ask("comment")}><${TermIcon} />Draft with Claude</button>
          <button disabled=${draft.busy} onClick=${() => ask("summary")}><${TermIcon} />Summarise thread</button>`}
      <span role="status" class="small soft">${note}</span></div>`;
}

function Thread({ thread, base, repo, number, ticked, onTick, onChanged }) {
  const [reply, setReply] = useState(null);
  const act = useAct(onChanged);
  const drafting = useAct();
  const [first, ...rest] = thread.comments;
  const where = `${thread.path}${thread.line ? `:${thread.line}` : ""}`;
  const draft = () => drafting.run(async () => {
    setReply((r) => r || "");
    const r = await post("agents/draft", { kind: "reply", object: "pr", repo, number, thread: thread.id });
    setReply((old) => (old && old.trim() ? `${old.trim()}\n\n${r.text}` : r.text));
  });
  const send = () => act.run(async () => { await post(`${base}/reply-thread`, { thread: thread.id, body: reply }); setReply(null); });
  const hunk = first && first.hunk ? first.hunk.split("\n").slice(-6).join("\n") : "";
  return html`<article class="thread ${thread.resolved ? "done" : ""}">
    <div class="row" style="gap: 6px 10px">
      ${!thread.resolved && html`<button role="checkbox" class="tick" aria-checked=${ticked ? "true" : "false"} aria-label="Select the thread on ${where}" onClick=${onTick}>
        ${ticked && html`<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M3 7.2l2.6 2.6L11 4.4" /></svg>`}</button>`}
      <span class="small soft grow"><b style="color: var(--ink)">${(first && first.author) || "deleted account"}</b> · ${first && ago(first.createdAt)} · <span class="mono" style="color: var(--ink); overflow-wrap: anywhere">${where}</span></span>
      ${thread.outdated && html`<span class="badge dim">outdated</span>`}${thread.resolved && html`<span class="badge dim">resolved</span>`}</div>
    ${hunk && html`<pre class="codeblock" style="font-size: 12.5px; white-space: pre-wrap; overflow-wrap: anywhere">${hunk}</pre>`}
    ${first && html`<${Md} text=${first.body} />`}
    ${rest.map((c) => html`<div class="stack" style="gap: 2px; padding-left: 12px; border-left: 1px solid var(--rule)"><span class="mono soft" style="font-size: 12.5px">${c.author} · ${ago(c.createdAt)}</span><${Md} text=${c.body} /></div>`)}
    <${Err} text=${act.error || drafting.error} />
    ${reply === null
      ? html`<div class="row"><button disabled=${drafting.busy} onClick=${draft}><${TermIcon} />Reply with Claude</button>
          <button class="plain" onClick=${() => setReply("")}>Reply</button>
          <button class="plain" disabled=${act.busy} onClick=${() => act.run(() => post(`${base}/${thread.resolved ? "reopen" : "resolve"}-thread`, { thread: thread.id }))}>${thread.resolved ? "Reopen" : "Resolve"}</button></div>`
      : html`<div class="stack" style="gap: 6px; padding: 10px 12px; border: 1.5px dashed var(--ink); border-radius: 10px">
          <span class="eyebrow">${drafting.busy ? "Drafting · reading the thread and the diff…" : "Your reply"}</span>
          <textarea aria-label="Reply on ${where}" rows="3" value=${reply} onInput=${(e) => setReply(e.target.value)}></textarea>
          <div class="row"><button class="primary" disabled=${act.busy || drafting.busy || !reply.trim()} onClick=${send}>Post reply</button>
            <button class="link" onClick=${() => setReply(null)}>Discard</button></div></div>`}
  </article>`;
}

const threadPin = (t) => ({ kind: "thread", label: `${t.path}${t.line ? `:${t.line}` : ""} (${t.id})` });

// 006 FR-018: tick threads, then "Address N threads…" opens Launch with the address action and those threads pinned.
function Threads({ threads, base, repo, number, picked, setPicked, onChanged }) {
  const open = threads.filter((t) => !t.resolved);
  const ticked = open.filter((t) => picked.has(t.id));
  const all = open.length > 0 && ticked.length === open.length;
  const [showDone, setShowDone] = useState(false);
  const done = threads.filter((t) => t.resolved);
  const toggle = (id) => setPicked((p) => { const n = new Set(p); if (!n.delete(id)) n.add(id); return n; });
  const address = ticked.length ? ticked : open;
  const here = `${repo}#${number}`;
  return html`${open.length > 0 && html`<div class="notice"><span class="grow" style="font-weight: 600">${count(open.length, "open review thread")}${ticked.length ? ` · ${ticked.length} ticked` : " · tick the ones an agent should address"}</span>
      <button class="plain" onClick=${() => setPicked(all ? new Set() : new Set(open.map((t) => t.id)))}>${all ? "Clear selection" : "Select all"}</button>
      <button class="pen" onClick=${() => launch({ verb: "address", covers: [{ kind: "pr", repo, number }], pins: address.map(threadPin), from: { view: "Work", ref: here } })}><${TermIcon} />Address ${count(address.length, "thread")}…</button></div>`}
    ${open.map((t) => html`<${Thread} key=${t.id} thread=${t} base=${base} repo=${repo} number=${number} ticked=${picked.has(t.id)} onTick=${() => toggle(t.id)} onChanged=${onChanged} />`)}
    ${done.length > 0 && html`<button class="link" style="align-self: flex-start" aria-expanded=${showDone ? "true" : "false"} onClick=${() => setShowDone(!showDone)}>${showDone ? "Hide" : "Show"} ${count(done.length, "resolved thread")}</button>`}
    ${showDone && done.map((t) => html`<${Thread} key=${t.id} thread=${t} base=${base} repo=${repo} number=${number} onChanged=${onChanged} />`)}`;
}

// A file's diff as rows with old and new line numbers. Lines outside a hunk (the header) are dropped.
function diffRows(text) {
  const rows = [];
  let a = 0;
  let b = 0;
  for (const line of String(text || "").split("\n")) {
    const hunk = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$/.exec(line);
    if (hunk) { a = Number(hunk[1]); b = Number(hunk[2]); rows.push({ kind: "hunk", text: line }); continue; }
    if (!a && !b) continue;
    if (line.startsWith("+")) rows.push({ kind: "add", b: b++, text: line.slice(1) });
    else if (line.startsWith("-")) rows.push({ kind: "del", a: a++, text: line.slice(1) });
    else if (line.startsWith("\\")) rows.push({ kind: "note", text: line });
    else if (line.startsWith(" ") || line === "") rows.push({ kind: "ctx", a: a++, b: b++, text: line.slice(1) });
  }
  while (rows.length && rows[rows.length - 1].kind === "ctx" && rows[rows.length - 1].text === "") rows.pop();
  return rows;
}

// One file in Files changed (006 FR-020, FR-021): opens to its hunks with line numbers and the review notes at their lines.
// A large or binary file waits for "load the diff".
function FileDiff({ base, file, threads }) {
  const [open, setOpen] = useState(false);
  const [asked, setAsked] = useState(!file.large);
  const diff = useLoad(() => (open && asked ? api(`${base}/diff${params({ path: file.path })}`) : Promise.resolve(null)), [open, asked, file.path]);
  const notes = threads.filter((t) => t.path === file.path);
  const at = (n) => notes.filter((t) => t.line === n);
  const loose = notes.filter((t) => !t.line);
  const rows = diff.data ? diffRows(diff.data) : [];
  return html`<div class="filediff">
    <button class="fileline" aria-expanded=${open ? "true" : "false"} onClick=${() => setOpen(!open)}>
      <${Chevron} right=${!open} /><span class="mono grow" style="overflow-wrap: anywhere">${file.path}</span>
      ${notes.length > 0 && html`<span class="badge dim">${count(notes.length, "note")}</span>`}
      <span class="mono small"><span class="add">+${file.additions}</span> <span class="del">−${file.deletions}</span></span></button>
    ${open && !asked && html`<div class="row" style="padding: 8px 12px"><span class="small soft grow">${file.binary ? "A binary file: no lines to show." : `${file.additions + file.deletions} lines changed.`}</span>
      ${!file.binary && html`<button onClick=${() => setAsked(true)}>Large file — load the diff</button>`}</div>`}
    ${open && asked && html`<${Err} text=${diff.error} />${!diff.data && !diff.error && html`<p class="small soft" style="padding: 8px 12px">Loading…</p>`}
      ${loose.length > 0 && html`<div class="diffnotes">${loose.map((t) => html`<${DiffNote} thread=${t} />`)}</div>`}
      ${diff.data !== null && html`<div class="diffbox"><table class="diff"><tbody>${rows.map((r) => html`
        <tr class=${r.kind}><td class="ln">${r.a || ""}</td><td class="ln">${r.b || ""}</td><td class="code">${r.kind === "add" ? "+" : r.kind === "del" ? "−" : " "}${r.text}</td></tr>
        ${r.b && at(r.b).length > 0 && html`<tr class="notes"><td colspan="3">${at(r.b).map((t) => html`<${DiffNote} thread=${t} />`)}</td></tr>`}`)}</tbody></table></div>`}`}
  </div>`;
}

const DiffNote = ({ thread }) => {
  const first = thread.comments[0];
  return html`<div class="diffnote ${thread.resolved ? "done" : ""}"><span class="small soft"><b style="color: var(--ink)">${(first && first.author) || "deleted account"}</b>${thread.resolved ? " · resolved" : ""}${thread.outdated ? " · outdated" : ""}${thread.comments.length > 2 ? ` · ${thread.comments.length - 1} replies` : thread.comments.length === 2 ? " · 1 reply" : ""}</span>
    ${first && html`<${Md} text=${first.body} />`}</div>`;
};

function FilesChanged({ base, threads }) {
  const files = useLoad(() => api(`${base}/files`), [base]);
  if (files.error) return html`<${Err} text=${files.error} />`;
  if (!files.data) return html`<p class="soft">Loading…</p>`;
  if (!files.data.length) return html`<p class="soft">No files changed.</p>`;
  return html`<div class="stack" style="gap: 6px">${files.data.map((f) => html`<${FileDiff} key=${f.path} base=${base} file=${f} threads=${threads} />`)}</div>`;
}

// 006 FR-022: the failed step's log, its error lines marked, and the full log a click away.
function FailedStep({ repo, id }) {
  const step = useLoad(() => api(`runs/${repo}/${id}/failed-step`), [repo, id]);
  const [full, setFull] = useState(null);
  const logs = useAct();
  if (step.error) return html`<${Err} text=${step.error} />`;
  if (!step.data) return html`<p class="soft">Loading…</p>`;
  const d = step.data;
  const errors = d.lines.filter((l) => l.error).length;
  return html`<div class="stack" style="gap: 8px">
    ${d.job ? html`<p style="font-weight: 600; overflow-wrap: anywhere">Failed: ${d.job}${d.step ? html` › ${d.step}` : ""}</p>
      <span class="small soft">${count(d.lines.length, "line")}${errors ? `, ${count(errors, "error line")} marked` : ""}</span>
      ${d.lines.length ? html`<ol class="steplog" aria-label="Log of the failed step">${d.lines.map((l) => html`<li class=${l.error ? "err" : ""} value=${l.n}>${l.error && html`<span class="sr">error: </span>`}${l.text}</li>`)}</ol>`
        : html`<p class="small soft">GitHub kept no log for this step.</p>`}`
      : html`<p class="soft">No job failed in this run.</p>`}
    <${Err} text=${logs.error} />
    <div class="row">${d.log_url && html`<a href=${d.log_url} target="_blank" rel="noreferrer noopener">The job on GitHub</a>`}
      <button class="plain" disabled=${logs.busy} onClick=${() => logs.run(async () => setFull(full === null ? await api(`runs/${repo}/${id}/log?all=1`) : null))}>${full === null ? "Full log here" : "Hide the full log"}</button></div>
    ${full !== null && html`<div class="log">${full}</div>`}</div>`;
}

const defs = (pairs) => html`<dl class="defs">${pairs.filter(([, v]) => v !== null && v !== undefined && v !== "").map(([k, v]) => html`<dt>${k}</dt><dd>${v}</dd>`)}</dl>`;
const labelList = (labels) => ((labels || []).length ? html`<span class="labels">${labels.map((l) => html`<span class="label" style="padding-right: 8px">${l.name}</span>`)}</span>` : "none");
const partOf = (body) => { const m = /^Part of\s+(\S+)/m.exec(body || ""); return m ? m[1] : null; };

function IssueDetail({ repo, number, frame, onChanged }) {
  const { data, error, reload } = useLoad(() => api(`issues/${repo}/${number}`), [repo, number]);
  const act = useAct(async () => { await reload(); onChanged(); });
  if (error && !data) return html`<${Err} text=${error} />`;
  if (!data) return html`<p class="soft">Loading…</p>`;
  const open = data.state === "OPEN";
  const base = `issues/${repo}/${number}`;
  const assignees = (data.assignees || []).map((a) => a.login);
  const facts = { failing: false, untriaged: !(data.labels || []).length, openThreads: 0, reviews: 0 };
  const conversation = html`<div class="body"><${Md} text=${data.body} /></div>
    <${Comments} list=${data.comments} />
    <${Err} text=${act.error || error} />
    <${Comment} busy=${act.busy} object="issue" repo=${repo} number=${number} onSend=${(body) => act.run(() => post(`${base}/comment`, { body }))} />`;
  return html`<${ItemFrame} kind="issue" repo=${repo} refText=${`${repo}#${number}`} title=${data.title} state=${data.state} stateCls=${open ? "" : "dim"}
    gh=${html`<${GhActions} kind="issue" data=${data} repo=${repo} number=${number} base=${base} onDone=${async () => { await reload(); onChanged(); }} />`}
    facts=${[`opened by ${data.author && data.author.login} ${ago(data.createdAt)}`, assignees.length ? `assigned to ${assignees.join(", ")}` : "no assignee",
      count(data.comments.length, "comment"), (data.labels || []).map((l) => l.name).join(", ")]}
    details=${defs([["Part of", partOf(data.body)], ["Author", data.author && data.author.login], ["Labels", labelList(data.labels)],
      ["Assignee", assignees.join(", ") || "unassigned"], ["Milestone", data.milestone && data.milestone.title], ["Updated", ago(data.updatedAt)],
      ["Repository", `GlassineOS/${repo}`], ["On GitHub", html`<a href=${data.url} target="_blank" rel="noreferrer noopener">${repo}#${number}</a>`]])}
    launchRow=${open && frame.launchRow({ kind: "issue", facts })}
    sessions=${frame.sessions({ kind: "issue", facts })}
    sections=${[{ id: "talk", label: "Conversation", body: conversation }]} />`;
}

const CHECK_BADGE = (s) => (["failure", "error", "timed_out", "cancelled", "action_required", "startup_failure"].includes(s) ? ["fail", "bad"]
  : ["success", "skipped", "neutral", "completed"].includes(s) ? [s === "skipped" ? "skip" : "ok", ""] : ["run", "dim"]);

function PrDetail({ repo, number, frame, onChanged }) {
  const { data, error, reload } = useLoad(() => api(`prs/${repo}/${number}`), [repo, number]);
  const threads = useLoad(() => api(`prs/${repo}/${number}/threads`), [repo, number]);
  const [picked, setPicked] = useState(new Set());
  const act = useAct(async () => { await reload(); onChanged(); });
  if (error && !data) return html`<${Err} text=${error} />`;
  if (!data) return html`<p class="soft">Loading…</p>`;
  const open = data.state === "OPEN";
  const base = `prs/${repo}/${number}`;
  const here = `${repo}#${number}`;
  const openThreads = (threads.data || []).filter((t) => !t.resolved);
  // A push and a pull request event each report the same check.
  const checks = [...new Map(data.check_list.map((c) => [`${c.workflow}/${c.name}/${c.state}`, c])).values()];
  const reviews = (data.reviews || []).filter((r) => r.body || r.state !== "COMMENTED").map((r) => ({ ...r, badge: `review · ${String(r.state).toLowerCase().replaceAll("_", " ")}` }));
  const talk = [...data.comments, ...reviews].sort((a, b) => new Date(a.createdAt || a.submittedAt) - new Date(b.createdAt || b.submittedAt));
  const facts = { failing: data.checks === "failing", changesRequested: data.reviewDecision === "CHANGES_REQUESTED", openThreads: openThreads.length,
    reviews: reviews.filter((r) => r.body && r.state !== "APPROVED").length, threadPins: openThreads.filter((t) => picked.has(t.id)).map(threadPin) };
  const conversation = html`<div class="body"><${Md} text=${data.body} /></div>
    <${Comments} list=${talk} />
    ${threads.data && threads.data.length > 0 && html`<${Threads} threads=${threads.data} base=${base} repo=${repo} number=${number} picked=${picked} setPicked=${setPicked} onChanged=${threads.reload} />`}
    <${Err} text=${threads.error || act.error || error} />
    <${Comment} busy=${act.busy} object="pr" repo=${repo} number=${number} onSend=${(body) => act.run(() => post(`${base}/comment`, { body }))}
      onDraft=${(text) => launch({ verb: "review", covers: [{ kind: "pr", repo, number }], notes: text.trim() ? `The comment so far:\n${text}` : "", from: { view: "Work", ref: here } })} />`;
  const files = (data.files || []).length;
  const merged = data.state === "MERGED";
  const state = merged ? `Merged${data.mergedBy ? ` by ${data.mergedBy.login}` : ""}` : data.isDraft && open ? "DRAFT" : data.state;
  return html`<${ItemFrame} kind="pr" repo=${repo} refText=${here} title=${data.title}
    state=${state} stateCls=${open ? (data.checks === "failing" ? "bad" : "") : "dim"}
    gh=${html`<${GhActions} kind="pr" data=${data} repo=${repo} number=${number} base=${base} behind=${data.behind_by} onDone=${async () => { await reload(); onChanged(); }} />`}
    facts=${[`+${data.additions} −${data.deletions}`, count(files, "file"), typeof data.behind_by === "number" ? `${data.behind_by} behind` : "",
      `checks ${data.checks}`, (data.reviewDecision || "").toLowerCase().replaceAll("_", " "), open && data.open_threads ? count(data.open_threads, "open thread") : ""]}
    chips=${html`<${CheckChips} checks=${checks} />`}
    details=${defs([["Part of", partOf(data.body)], ["Branch", html`<span class="mono">${data.headRefName} → ${data.baseRefName}</span>`],
      ["Size", `+${data.additions} −${data.deletions}, ${count(files, "file")}`], ["Author", data.author && data.author.login], ["Labels", labelList(data.labels)],
      ["Assignee", (data.assignees || []).map((a) => a.login).join(", ") || "unassigned"], ["Reviews", (data.reviewDecision || "none").toLowerCase().replaceAll("_", " ")],
      ["State", `${data.isDraft ? "draft · " : ""}${data.state.toLowerCase()}${data.mergeStateStatus ? ` · ${String(data.mergeStateStatus).toLowerCase()}` : ""}`],
      ["Updated", ago(data.updatedAt)], ["Repository", `GlassineOS/${repo}`],
      ["Changed files", html`<ul class="mono small">${(data.files || []).map((f) => html`<li>${f.path}</li>`)}</ul>`],
      ["On GitHub", html`<a href=${data.url} target="_blank" rel="noreferrer noopener">${here}</a>`]])}
    launchRow=${open && frame.launchRow({ kind: "pr", facts })}
    sessions=${frame.sessions({ kind: "pr", facts })}
    sections=${[{ id: "talk", label: "Conversation", body: conversation }, { id: "files", label: `Files changed ${files}`, body: html`<${FilesChanged} base=${base} threads=${threads.data || []} />` }]} />`;
}

function duration(job) {
  if (!job.startedAt || !job.completedAt) return "";
  const s = Math.round((new Date(job.completedAt) - new Date(job.startedAt)) / 1000);
  return s < 0 ? "" : s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

function RunDetail({ repo, id, frame, onChanged }) {
  const { data, error, reload } = useLoad(() => api(`runs/${repo}/${id}`), [repo, id], 20000);
  if (error && !data) return html`<${Err} text=${error} />`;
  if (!data) return html`<p class="soft">Loading…</p>`;
  const running = data.status !== "completed";
  const failed = data.conclusion === "failure";
  const jobs = data.jobs || [];
  const facts = { failing: failed, openThreads: 0, reviews: 0 };
  const took = data.jobs && jobs.length ? duration({ startedAt: jobs[0].startedAt, completedAt: jobs[jobs.length - 1].completedAt }) : "";
  const summary = html`<${Err} text=${error} />${failed ? html`<${FailedStep} repo=${repo} id=${id} />`
    : html`<p class="soft">${running ? "Still running. The log is on GitHub until it ends." : `Ended: ${String(data.conclusion || "").toLowerCase()}.`}</p>`}`;
  return html`<${ItemFrame} kind="run" repo=${repo} refText=${`${repo} run ${id}`} title=${`${data.workflowName} · ${data.displayTitle}`}
    state=${String(data.conclusion || data.status).toUpperCase()} stateCls=${failed ? "bad" : running ? "dim" : ""}
    gh=${html`<${GhActions} kind="run" data=${data} repo=${repo} number=${id} base=${`runs/${repo}/${id}`} onDone=${async () => { await reload(); onChanged(); }} />`}
    facts=${[`${data.event} on ${data.headBranch}`, (data.headSha || "").slice(0, 7), took, ago(data.createdAt)]}
    chips=${html`<${CheckChips} checks=${jobs.map((j) => ({ name: j.name, state: j.conclusion || j.status, url: j.url }))} />`}
    details=${defs([["Workflow", data.workflowName], ["Trigger", `${data.event} on ${data.headBranch}`], ["Commit", html`<span class="mono">${(data.headSha || "").slice(0, 12)}</span>`],
      ["Jobs", html`<ul class="small">${jobs.map((j) => html`<li>${j.name} · ${j.conclusion || j.status}${duration(j) ? ` · ${duration(j)}` : ""}</li>`)}</ul>`],
      ["Updated", ago(data.updatedAt)], ["Repository", `GlassineOS/${repo}`],
      ["On GitHub", html`<a href=${data.url} target="_blank" rel="noreferrer noopener">${repo} run ${id}</a>`]])}
    launchRow=${!running && frame.launchRow({ kind: "run", facts })}
    sessions=${frame.sessions({ kind: "run", facts })}
    sections=${[{ id: "summary", label: failed ? "Failed step" : "Summary", body: summary }]} />`;
}

function NewIssue({ groups, initial, roadmap, onDone, onCancel }) {
  const [repo, setRepo] = useState(initial || "hub");
  const [onBoard, setOnBoard] = useState(Boolean(roadmap));
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const act = useAct();
  return html`<h2 id="h-item" style="font-size: 22px; font-weight: 600">New issue</h2>
    <div class="field"><span aria-hidden="true">Repository</span><${RepoPicker} value=${repo} onChange=${setRepo} groups=${groups} /></div>
    <label class="field"><span>Title</span><input value=${title} onInput=${(e) => setTitle(e.target.value)} /></label>
    <label class="field"><span>Description</span><textarea rows="6" placeholder="Markdown supported" value=${body} onInput=${(e) => setBody(e.target.value)}></textarea></label>
    <label class="row small"><input type="checkbox" style="min-height: 0" checked=${onBoard} onChange=${(e) => setOnBoard(e.target.checked)} /> Add to the roadmap</label>
    <${Err} text=${act.error} />
    <div class="row"><button class="primary" disabled=${act.busy || !title.trim()}
      onClick=${async () => { const r = await act.run(() => post(`issues/${repo}`, { title, body, roadmap: onBoard })); if (r) onDone(r); }}>Create</button>
      <button onClick=${onCancel}>Cancel</button></div>`;
}

function Dispatch({ groups, initial, onDone, onCancel }) {
  const [repo, setRepo] = useState(initial || "");
  const { data, error } = useLoad(() => (repo ? api(`workflows/${repo}`) : Promise.resolve([])), [repo]);
  const [file, setFile] = useState("");
  const [ref, setRef] = useState("main");
  const [confirm, dialog] = useConfirm();
  const act = useAct(onDone);
  const active = (data || []).filter((w) => w.state === "active");
  return html`${dialog}<h2 id="h-item" style="font-size: 22px; font-weight: 600">Run a workflow</h2>
    <${Err} text=${error || act.error} />
    <div class="field"><span aria-hidden="true">Repository</span><${RepoPicker} value=${repo} onChange=${(r) => { setRepo(r); setFile(""); }} groups=${groups} /></div>
    <label class="field"><span>Workflow</span><select value=${file} disabled=${!repo} onChange=${(e) => setFile(e.target.value)}>
      <option value="">Choose…</option>${active.map((w) => html`<option value=${w.path.split("/").pop()}>${w.name}</option>`)}</select></label>
    <label class="field"><span>Branch</span><input value=${ref} onInput=${(e) => setRef(e.target.value)} /></label>
    <div class="row"><button class="primary" disabled=${!file || act.busy} onClick=${() => confirm(
      { title: "Start this workflow?", text: `${file} of ${repo} on ${ref}. Some workflows publish things.`, label: "Start" },
      () => act.run(() => post(`workflows/${repo}/${file}/dispatch`, { ref })),
    )}>Start workflow</button><button onClick=${onCancel}>Cancel</button></div>`;
}

// --- work: list --------------------------------------------------------------------------
function SyncLine({ onSynced }) {
  const { data, reload } = useLoad(() => api("work/status"), [], 15000);
  const act = useAct(async () => { await reload(); await onSynced(); });
  if (!data || !data.enabled) return null;
  const when = data.synced_at ? ago(new Date(data.synced_at * 1000)) : "not yet";
  return html`<div class="row small soft" style="gap: 4px 12px">
    <span role="status">${data.error ? html`<b>Last sync failed: ${data.error}.</b> Showing what was synced ${when}.` : `Synced with GitHub ${when}`}${data.ready ? "" : " · asking GitHub directly until the first sync finishes"}</span>
    <button class="link" disabled=${act.busy || data.running} onClick=${() => act.run(() => post("work/sync"))}>${act.busy ? "Syncing…" : "Refresh"}</button>
    <${Err} text=${act.error} /></div>`;
}

const ROWS = {
  issues: (i) => ({
    key: `${i.repo}#${i.number}`, repo: i.repo, number: i.number, ref: `${i.repo}#${i.number}`, title: i.title,
    sub: [i.labels.map((l) => l.name).join(" · "), i.comments ? count(i.comments, "comment") : ""].filter(Boolean).join(" · ") || (i.author && i.author.login) || "",
    state: i.state, pill: pillState("issue", i), at: i.updatedAt, object: "issue", labels: i.labels.map((l) => l.name), startable: i.state === "OPEN",
  }),
  prs: (p) => ({
    key: `${p.repo}#${p.number}`, repo: p.repo, number: p.number, ref: `${p.repo}#${p.number}`, title: p.title,
    sub: `${p.headRefName} → ${p.baseRefName}`, agent: p.headRefName.startsWith("agent/"), object: "pr", pill: pillState("pr", p), at: p.updatedAt, labels: p.labels.map((l) => l.name), startable: p.state === "OPEN",
    state: p.state !== "OPEN" ? p.state : p.isDraft ? "Draft" : p.checks === "failing" ? "Failing" : p.checks === "pending" ? "Checks" : p.checks === "passing" ? "Ready" : "Open",
    icon: p.state !== "OPEN" ? "pass" : p.checks === "failing" ? "fail" : p.checks === "pending" ? "run" : p.checks === "passing" ? "pass" : "open",
  }),
  actions: (r) => ({
    key: `${r.repo}/${r.databaseId}`, repo: r.repo, number: r.databaseId, workflow: r.workflowName, ref: `${r.workflowName} #${r.databaseId}`, title: `${r.repo} · ${r.displayTitle}`,
    sub: `${r.event} on ${r.headBranch} · ${(r.headSha || "").slice(0, 7)}`, agent: (r.headBranch || "").startsWith("agent/"), object: "run", pill: pillState("run", r), at: r.createdAt, labels: [], startable: r.status === "completed",
    state: r.status !== "completed" ? "Running" : r.conclusion === "success" ? "Passed" : r.conclusion || "Done",
    icon: r.status !== "completed" ? "run" : r.conclusion === "failure" ? "fail" : r.conclusion === "success" ? "pass" : "open",
  }),
};

const STATES = {
  issues: [["open", "Open"], ["closed", "Closed"], ["all", "All"]],
  prs: [["open", "Open"], ["merged", "Merged"], ["closed", "Closed"], ["all", "All"]],
  actions: [["", "Any"], ["in_progress", "Running"], ["queued", "Queued"], ["failure", "Failed"], ["success", "Passed"]],
};

// repo:kernel label:driver assignee:me state:closed, and the rest is words to look for.
function parseFilter(text) {
  const out = { words: "" };
  out.words = text.replace(/(^|\s)(repo|label|assignee|state):(\S+)/g, (_m, _s, key, value) => { out[key] = value; return " "; }).trim();
  return out;
}

const NEEDS = {
  issues: { order: ["Needs you", "Untriaged", "Everything else"], of: (r, waiting, mine) => (waiting || mine.has(r.key) ? "Needs you" : !r.labels.length && r.state === "OPEN" ? "Untriaged" : "Everything else") },
  prs: { order: ["Needs you", "From agent sessions", "Everything else"], of: (r, waiting, _mine, session) => (waiting || r.state === "Failing" || r.state === "Ready" ? "Needs you" : r.agent || session ? "From agent sessions" : "Everything else") },
  actions: { order: ["Failed", "Running", "Recent"], of: (r) => (r.icon === "fail" ? "Failed" : r.icon === "run" ? "Running" : "Recent") },
};

function readWorkFilter() {
  try { return JSON.parse(sessionStorage.getItem("work-filter")) || {}; } catch { return {}; }
}

const MAX_ROW_CHIPS = 3;

function WorkRow({ row, tab, scope, sessions, action }) {
  const open = hash("work", { tab, repo: scope, at: row.repo, item: row.number });
  const kind = { issues: "issue", prs: "pr", actions: "run" }[tab];
  // Only a plain click: a link opened in a new tab is just the item.
  // 005 SC-001: the row's blue action opens Launch on the row's item, from Work.
  const launchIt = () => launch({ action: action.id, covers: [{ kind, repo: row.repo, number: row.number }], from: { view: "Work", ref: `${row.repo}#${row.number}` } });
  // Every session on the item (002 FR-019), each opening the item, where its session shows (002 FR-018).
  const shown = sessions.slice(0, MAX_ROW_CHIPS);
  return html`<div class="wrow">
    <${ItemPill} kind=${kind} repo=${row.repo} number=${row.number} workflow=${row.workflow} state=${row.pill} plain />
    <a class="t" href=${open}><span class="line"><b>${row.title}</b></span><span class="small soft sub">${row.sub}</span></a>
    ${shown.length > 0 && html`<span class="row" style="gap: 6px">${shown.map((s) => html`<${SessionChip} key=${s.name} session=${s} href=${open} />`)}
      ${sessions.length > shown.length && html`<a class="small" href=${open}>${sessions.length - shown.length} more</a>`}</span>`}
    <span class="state">${row.state}</span><span class="age">${age(row.at)}</span>
    ${action && html`<button class="start" title=${`${action.summary} Opens Launch: the planner runs first, and you read its plan. ${action.ceiling}`} onClick=${launchIt}><${TermIcon} />${action.title}</button>`}
  </div>`;
}

// Work's tabs. The queue is its own view of the pull requests, so it has the page to itself.
function Work({ query, asks }) {
  return query.tab === "queue" ? html`<${WorkQueue} />` : html`<${WorkLists} query=${query} asks=${asks} />`;
}

function WorkLists({ query, asks }) {
  const overview = useLoad(() => api("overview"), []);
  const sessions = useSessions();
  // What the address says, so an item can be linked to and Back returns to the list as it was.
  const tab = query.tab || "issues";
  const scope = query.repo || "";
  const go = (patch) => { location.hash = hash("work", { tab, repo: scope, ...patch }); };
  // In this tab of the browser, so a reload keeps your list and k / j still walk it.
  const kept = useRef(readWorkFilter()).current;
  const [states, setStates] = useState({ issues: "open", prs: "open", ...kept.states, ...(query.status ? { actions: query.status } : {}) });
  const [groupBy, setGroupBy] = useState(kept.groupBy || "needs");
  const [search, setSearch] = useState(kept.applied || "");
  const [applied, setApplied] = useState(kept.applied || "");
  useEffect(() => { try { sessionStorage.setItem("work-filter", JSON.stringify({ states, groupBy, applied })); } catch { /* it only helps */ } }, [states, groupBy, applied]);
  const [byMeaning, setByMeaning] = useState(false);
  const [allRepos, setAllRepos] = useState(false);
  const [panel, setPanel] = useState(query.new === "1" ? "new" : null);
  const [notice, setNotice] = useState(null);
  const [phases, setPhases] = useState({}); // session name → embedded or background, as moved on this page; else its stored view
  useEffect(() => { if (query.new === "1") setPanel("new"); }, [query.new]);
  const groups = overview.data ? overview.data.groups : [];
  const filter = parseFilter(applied);
  const repo = filter.repo || scope;
  const state = filter.state || states[tab];
  const assignee = filter.assignee === "me" ? "@me" : filter.assignee || "";
  const load = async () => {
    if (tab === "issues") return { tab, rows: await api(`issues${params({ repo, state, search: filter.words, assignee })}`) };
    return { tab, rows: await (tab === "prs" ? api(`prs${params({ repo, state })}`) : api(`runs${params({ repo, status: state })}`)) };
  };
  const loaded = useLoad(load, [tab, repo, state, assignee, filter.words], 20000);
  const { error, loading, reload } = loaded;
  // The list of the tab you just left is still here until the new one arrives, and has other fields.
  const data = loaded.data && loaded.data.tab === tab ? loaded.data.rows : null;
  const mineList = useLoad(() => (tab === "issues" ? api(`issues${params({ repo, state: "open", assignee: "@me" })}`).catch(() => []) : Promise.resolve([])), [tab, repo], 60000);
  const offered = useLoad(() => api(`agents/actions${params({ object: { issues: "issue", prs: "pr", actions: "run" }[tab] })}`).catch(() => []), [tab]);
  const meaning = useLoad(() => (byMeaning && filter.words && tab !== "actions"
    ? api(`work/search${params({ q: filter.words, kind: tab === "prs" ? "pr" : "issue", repo, state })}`) : Promise.resolve(null)), [byMeaning, filter.words, tab, repo, state]);
  const list = sessions.data || [];
  const sessionOf = (row) => sessionsOn(row, list)[0];
  const needle = filter.words.toLowerCase();
  const found = meaning.data && byMeaning && filter.words && tab !== "actions" ? meaning.data.results : null;
  const rows = (found
    ? found.map((h) => ({ ...ROWS[tab](h.row), sub: h.passage.replace(/\s+/g, " ").slice(0, 140) }))
    : (data || []).map(ROWS[tab]).filter((r) => tab === "issues" || !needle || `${r.title} ${r.ref} ${r.sub}`.toLowerCase().includes(needle)))
    .filter((r) => !filter.label || r.labels.includes(filter.label));
  const mine = new Set((mineList.data || []).map((i) => `${i.repo}#${i.number}`));
  const layerOf = new Map(groups.flatMap((g) => g.repos.map((r) => [r.name, g.title])));
  const startFor = (r) => {
    if (!r.startable) return null;
    const failing = r.icon === "fail";
    return (offered.data || []).find((a) => a.plan && !a.needs && (!a.when || a.when === (failing ? "failing" : "not-failing"))) || null;
  };
  const sections = () => {
    if (groupBy === "none") return [[null, rows]];
    const keyOf = groupBy === "repo" ? (r) => r.repo : groupBy === "layer" ? (r) => layerOf.get(r.repo) || "Unplaced"
      : (r) => { const s = sessionOf(r); return NEEDS[tab].of(r, s && s.agent.waiting, mine, s); };
    const by = new Map(groupBy === "needs" ? NEEDS[tab].order.map((k) => [k, []]) : []);
    for (const r of rows) by.set(keyOf(r), [...(by.get(keyOf(r)) || []), r]);
    return [...by.entries()].filter(([, v]) => v.length);
  };
  const shown = sections().flatMap(([, v]) => v); // k and j follow the order on the page
  const itemRepo = query.at || query.repo;
  const itemNumber = query.item ? Number(query.item) : null;
  const current = itemNumber && itemRepo ? { repo: itemRepo, number: itemNumber, object: { issues: "issue", prs: "pr", actions: "run" }[tab], key: `${itemRepo}#${itemNumber}` } : null;
  const position = current ? shown.findIndex((r) => r.repo === current.repo && r.number === current.number) : -1;
  const stepTo = (delta) => { const r = shown[position + delta]; if (position >= 0 && r) go({ at: r.repo, item: r.number }); };
  const step = useRef(stepTo);
  step.current = stepTo;
  useEffect(() => {
    if (!current) return undefined;
    const on = (e) => {
      if (e.ctrlKey || e.metaKey || e.altKey || (e.key !== "k" && e.key !== "j")) return;
      if (e.target.closest("input, textarea, select, [contenteditable], .xterm, dialog")) return;
      step.current(e.key === "j" ? 1 : -1);
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [Boolean(current)]);
  const switchTab = (t) => { setPanel(null); go({ tab: t }); };
  const counts = overview.data ? overview.data.totals : null;
  const scoped = groups.flatMap((g) => g.repos).find((r) => r.name === repo);
  const TABS = [["issues", "Issues", scoped ? scoped.issues : counts && counts.issues], ["prs", "Pull requests", scoped ? scoped.prs : counts && counts.prs], ["actions", "Actions", null], ["queue", "Queue", null]];
  const stateWord = (STATES[tab].find(([v]) => v === state) || [state, state])[1];
  if (current) {
    const here = `${current.repo}#${current.number}`;
    const on = sessionsOn(current, list);
    // Where each session on the item shows: as moved on this page, else its stored view. Embedded only when it was put here.
    const phaseOf = (s) => phases[s.name] || (s.agent.view && s.agent.view.mode === "embedded" && s.agent.view.where === "Work" && (!s.agent.view.ref || s.agent.view.ref === here) ? "embedded" : "background");
    // Moved here: shown so at once, and kept by hubd for the next page that draws it.
    const place = (name, mode) => {
      setPhases((p) => ({ ...p, [name]: mode }));
      post("agents/view", { name, mode, where: "Work", ref: here }).then(() => sessions.reload(), () => {});
    };
    const frame = {
      launchRow: ({ kind, facts }) => html`<${LaunchRow} key=${current.key} kind=${kind} repo=${current.repo} number=${current.number} facts=${facts} />`,
      sessions: ({ kind, facts }) => html`<${SessionsOn} key=${current.key} kind=${kind} repo=${current.repo} number=${current.number} facts=${facts} sessions=${on}
        phaseOf=${phaseOf} place=${place} setPhase=${(name, m) => setPhases((p) => ({ ...p, [name]: m }))} asks=${asks} onReload=${() => sessions.reload()} />`,
    };
    const props = { key: current.key, repo: current.repo, frame, onChanged: reload };
    return html`<main class="page close">
      <div class="crumbs"><a href=${hash("work", { tab, repo: scope })} style="font-weight: 600">← ${TABS.find((t) => t[0] === tab)[1]}</a>
        <span class="mono soft grow" style="font-size: 13px">${position >= 0 ? `${position + 1} of ${shown.length} listed` : "not in the list"} · ${stateWord} · ${repo || "all repositories"}</span>
        <button class="square" aria-label="Previous item" disabled=${position <= 0} onClick=${() => stepTo(-1)}><svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M3 10l5-5 5 5" /></svg></button>
        <button class="square" aria-label="Next item" disabled=${position < 0 || position >= shown.length - 1} onClick=${() => stepTo(1)}><svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M3 6l5 5 5-5" /></svg></button>
        <span class="mono soft" style="font-size: 12px">k / j</span></div>
      <${Err} text=${notice} />
      ${tab === "issues" ? html`<${IssueDetail} number=${current.number} ...${props} />`
        : tab === "prs" ? html`<${PrDetail} number=${current.number} ...${props} />`
        : html`<${RunDetail} id=${current.number} ...${props} />`}
    </main>`;
  }
  const chips = [...groups.flatMap((g) => g.repos)].sort((a, b) => (b.issues + b.prs) - (a.issues + a.prs));
  const visible = allRepos ? chips : chips.filter((r, i) => i < 5 || r.name === scope);
  const layer = scoped ? layerOf.get(scoped.name) : null;
  return html`<main class="page close">
    <h1 class="sr">Work</h1>
    <div class="row" style="gap: 10px 14px"><span class="eyebrow soft">Repository</span>
      <div role="radiogroup" aria-label="Repository" class="row" style="flex: 1 1 400px; gap: 6px">
        <button role="radio" class="pill mono" aria-checked=${!scope ? "true" : "false"} onClick=${() => go({ repo: undefined })}>All</button>
        ${visible.map((r) => html`<button role="radio" class="pill mono" aria-checked=${scope === r.name ? "true" : "false"} onClick=${() => go({ repo: r.name })}>${r.name}</button>`)}
        ${chips.length > 5 && html`<button class="addlabel" onClick=${() => setAllRepos(!allRepos)}>${allRepos ? "fewer" : "more…"}</button>`}</div>
      <button onClick=${() => launch({ repos: repo ? [repo] : undefined, from: { view: "Work" } })}>${repo ? `＋ New in ${repo}…` : "＋ New work…"}</button>
      <button class="primary" onClick=${() => setPanel(tab === "actions" ? "dispatch" : "new")}>${tab === "actions" ? "Run workflow…" : repo ? `New issue in ${repo}` : "New issue"}</button></div>
    <p style="font-size: 17px; line-height: 1.4"><span class="mono" style="font-weight: 600">${repo ? `GlassineOS/${repo}` : `GlassineOS · all ${groups.flatMap((g) => g.repos).length} repositories`}</span>
      <span class="soft"> · ${repo ? (layer || "") : groupBy === "needs" ? "grouped by what needs you" : "all"}</span></p>
    ${panel && html`<div class="panel">${panel === "new" ? html`<${NewIssue} groups=${groups} initial=${repo || query.repo} roadmap=${query.roadmap === "1"} onCancel=${() => setPanel(null)}
        onDone=${(r) => { setPanel(null); reload(); setNotice(r.roadmap_error ? `Created, but not added to the roadmap: ${r.roadmap_error}` : null); go({ at: r.repo, item: r.number, new: undefined, roadmap: undefined }); }} />`
      : html`<${Dispatch} key=${repo} groups=${groups} initial=${repo} onCancel=${() => setPanel(null)} onDone=${() => { setPanel(null); reload(); }} />`}</div>`}
    <div role="tablist" aria-label="Work type" class="tabs">
      ${TABS.map(([id, label, n]) => html`<button role="tab" aria-selected=${tab === id ? "true" : "false"} onClick=${() => switchTab(id)}>${label}${n != null && html` <span class="count">${n}</span>`}</button>`)}
    </div>
    <div class="filters">
      <form class="searchbox" role="search" onSubmit=${(e) => { e.preventDefault(); setApplied(search); }}>
        <${SearchIcon} /><label class="sr" for="work-search">Filter</label>
        <input id="work-search" type="search" placeholder=${byMeaning ? "Describe what you're looking for" : "repo:kernel label:driver assignee:me, or words"} value=${search} onInput=${(e) => { setSearch(e.target.value); if (!e.target.value) setApplied(""); }} /></form>
      ${tab !== "actions" && html`<button class="pill" aria-pressed=${byMeaning ? "true" : "false"} onClick=${() => setByMeaning(!byMeaning)}>By meaning</button>`}
      <label class="field"><span>State</span><select value=${states[tab]} onChange=${(e) => setStates({ ...states, [tab]: e.target.value })}>
        ${STATES[tab].map(([v, t]) => html`<option value=${v}>${t}</option>`)}</select></label>
      <label class="field"><span>Group by</span><select value=${groupBy} onChange=${(e) => setGroupBy(e.target.value)}>
        <option value="needs">${tab === "actions" ? "Outcome" : "What needs me"}</option><option value="layer">Layer</option><option value="repo">Repository</option><option value="none">None</option></select></label>
    </div>
    <${SyncLine} onSynced=${reload} />
    ${found && meaning.data.semantic !== "ready" && html`<div class="notice quiet"><span>Search by meaning isn't available (${meaning.data.semantic}), so this matched words only.</span></div>`}
    <${Err} text=${error || notice || meaning.error} />
    ${sections().map(([name, group]) => html`<section aria-label=${name || TABS.find((t) => t[0] === tab)[1]} class="stack" style="gap: 6px">
      ${name && html`<h2 class="eyebrow">${name} <span class="soft">${group.length}</span></h2>`}
      <div class="wlist">${group.map((r) => html`<${WorkRow} key=${r.key} row=${r} tab=${tab} scope=${scope} sessions=${sessionsOn(r, list)} action=${startFor(r)} />`)}</div></section>`)}
    ${data && !rows.length && html`<p class="soft">Nothing here.</p>`}
    ${!data && loading && html`<p class="soft">Loading…</p>`}
    ${rows.length > 0 && html`<p class="small soft">Open an item to work on it full width, and k / j steps through this list from there. The button on a row opens Launch with its most likely Claude action.</p>`}
  </main>`;
}

// --- docs ----------------------------------------------------------------------------------
const INDEX_WORD = {
  current: ["dim", "Index matches the docs head."],
  building: ["dim", "The docs CI is publishing the head."],
  stale: ["mark", "Head moved and no docs run is active."],
  failed: ["bad", "The docs CI failed; search still uses the published index."],
};

function urlPath(url) {
  try { const u = new URL(url); return u.pathname.replace(/^\//, "") + u.hash; } catch (e) { return url; }
}

// Knowledge: the docs search, until the Knowledge view of PR 15 replaces it (001 FR-001).
function Knowledge() {
  const status = useLoad(() => api("docs/status"), [], 60000);
  const [q, setQ] = useState("");
  const [results, setResults] = useState(null);
  const search = useAct();
  const reindex = useAct(status.reload);
  const s = status.data;
  const top = results && results.results.length ? results.results[0].score || 1 : 1;
  const auto = !s ? "" : s.auto.kind === "waiting" ? `Starts the docs CI in ${Math.ceil(s.auto.seconds / 60)} min · once for this commit`
    : s.auto.kind === "done" ? "Already started once for this commit: run it by hand." : s.state === "failed" ? "Run it by hand." : "Nothing to do.";
  const run = s && s.latest_run;
  return html`<main class="page"><div class="columns">
    <section class="wide stack" style="gap: 20px" aria-labelledby="h-search">
      <div class="stack tight"><${Eyebrow} soft>docs.glassine.org · search by meaning<//><h1 id="h-search">Knowledge</h1></div>
      <form role="search" class="row" style="gap: 12px" onSubmit=${(e) => { e.preventDefault(); search.run(async () => setResults(await api(`docs/search${params({ q })}`))); }}>
        <div class="searchbox big" style="flex: 1 1 360px"><${SearchIcon} /><label class="sr" for="docs-q">Search the docs</label>
          <input id="docs-q" type="search" placeholder="Ask in plain words: how do I get back into recovery?" value=${q} onInput=${(e) => setQ(e.target.value)} /></div>
        <button class="primary" style="min-height: 52px; padding: 0 20px" disabled=${search.busy || !q.trim()}>Search</button></form>
      <${Err} text=${search.error} />
      ${search.busy && html`<p class="soft small">Searching… the first search downloads the model once.</p>`}
      ${results && html`<span class="small soft">${count(results.results.length, "passage")} · searched the index at <span class="mono">${(results.commit || "").slice(0, 7)}</span></span>
        <ol>${results.results.map((h) => html`<li class="hit">
          <div class="row" style="gap: 4px 12px; align-items: baseline"><a href=${h.url} target="_blank" rel="noreferrer noopener">${h.title}${h.heading && h.heading !== h.title ? ` › ${h.heading}` : ""}</a>
            <span class="mono soft" style="font-size: 12.5px">${urlPath(h.url)}</span></div>
          <p>${h.text.length > 400 ? `${h.text.slice(0, 400)}…` : h.text}</p>
          ${h.score != null && html`<div class="match"><span class="bar ink"><i style="width: ${Math.round(h.score / top * 100)}%"></i></span>match ${(h.score / top).toFixed(2)}</div>`}
        </li>`)}</ol>
        ${!results.results.length && html`<p class="soft">Nothing found. That doesn't prove it isn't documented.</p>`}`}
    </section>
    <aside class="aside panel" aria-labelledby="h-index" style="gap: 18px; padding: 24px">
      <h2 id="h-index" class="eyebrow">Search index</h2>
      <${Err} text=${status.error || reindex.error} />
      ${s && html`<div class="row"><span class="badge ${INDEX_WORD[s.state][0]}">${s.state}</span><span class="grow" style="font-weight: 500">${INDEX_WORD[s.state][1]}</span></div>
        <ol aria-label="Index states" class="steps">${["current", "building", "stale", "failed"].map((n) => html`<li aria-current=${n === s.state ? "step" : "false"}>${n}</li>`)}</ol>
        <dl class="defs"><dt>Published</dt><dd class="mono">${s.published.slice(0, 7)}</dd>
          <dt>Docs head</dt><dd class="mono">${s.head.slice(0, 7)}</dd>
          <dt>Size</dt><dd>${s.chunks} passages · ${s.profile}</dd>
          <dt>CI</dt><dd>${run ? html`<a href=${run.url} target="_blank" rel="noreferrer noopener">${run.conclusion || run.status}</a>, ${ago(run.createdAt)}` : "no recent run"}</dd>
          <dt>Auto</dt><dd>${auto}</dd></dl>
        <div class="row"><button class="primary" disabled=${reindex.busy || s.state === "current" || s.state === "building"} onClick=${() => reindex.run(() => post("docs/reindex"))}>Run docs CI now</button>
          <a class="button" href=${hash("work", { tab: "actions", repo: "docs" })}>Docs runs</a></div>
        <p class="small soft" style="border-top: 1px dotted var(--ink); padding-top: 14px">Agents query the same index through the tool server, so results here match what a session sees.</p>`}
    </aside></div></main>`;
}

// --- terminal ----------------------------------------------------------------------------------
async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Not a secure context (plain http on another address), or the browser said no.
    const area = document.createElement("textarea");
    area.value = text;
    document.body.append(area);
    area.select();
    const done = document.execCommand("copy");
    area.remove();
    return done;
  }
}

// OSC 52 from tmux: "c;<base64>". "?" asks to read the clipboard, which nothing here may.
function clipboardPayload(data) {
  const encoded = data.slice(data.indexOf(";") + 1);
  if (!encoded || encoded === "?") return null;
  try {
    return new TextDecoder().decode(Uint8Array.from(atob(encoded), (c) => c.charCodeAt(0)));
  } catch {
    return null;
  }
}

// `quiet`: beside a page you're using, so it takes the keyboard only when you click it.
// Terminals are on night paper (#121212), the --night token, in both themes.
const nightPaper = () => (getComputedStyle(document.documentElement).getPropertyValue("--night").trim() || "#121212");

function TerminalView({ name, onGone, focusRef, quiet }) {
  const box = useRef();
  const [note, setNote] = useState("Connecting…");
  const [copied, setCopied] = useState("");
  const [typing, setTyping] = useState(true);
  useEffect(() => {
    const term = new Terminal({
      cursorBlink: true, fontFamily: '"IBM Plex Mono", ui-monospace, monospace', fontSize: 14, scrollback: 5000,
      theme: { background: nightPaper(), foreground: "#eeeeee", cursor: "#eeeeee" },
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(box.current);
    fit.fit();
    if (!quiet) term.focus();
    if (focusRef) focusRef.current = () => term.focus();
    // Keys only reach the terminal with focus on it: without, Shift+Tab walks the page instead.
    // Focus lost to nothing (a re-render took the element, the window came back) returns to it.
    const toBody = () => { if (!quiet && (document.activeElement === document.body || !document.activeElement)) term.focus(); };
    const followed = () => setTimeout(toBody);
    const onFocus = () => setTyping(true);
    const onBlur = () => setTyping(false);
    term.textarea.addEventListener("focus", onFocus);
    term.textarea.addEventListener("blur", onBlur);
    document.addEventListener("focusout", followed);
    window.addEventListener("focus", followed);
    setTyping(document.activeElement === term.textarea);
    let hint;
    const copy = async (text) => {
      const done = await copyText(text);
      term.focus();
      setCopied(done ? `Copied ${count(text.length, "character")}` : "The browser didn't allow copying");
      clearTimeout(hint);
      hint = setTimeout(() => setCopied(""), 2500);
    };
    // A drag: tmux selects and sends the text here. Shift-drag: the terminal selects by itself,
    // which also works where a program in the pane takes the mouse.
    term.parser.registerOscHandler(52, (data) => {
      const text = clipboardPayload(data);
      if (text) copy(text);
      return true;
    });
    const selected = term.onSelectionChange(() => { if (term.hasSelection()) copy(term.getSelection()); });
    term.attachCustomKeyEventHandler((e) => {
      // Sent as a plain Enter, this would submit Claude's prompt. Ctrl+J is its new line in any terminal, and needs nothing of tmux.
      if (e.key === "Enter" && e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey) {
        if (e.type === "keydown" && ws.readyState === WebSocket.OPEN) ws.send(encoder.encode("\n"));
        e.preventDefault();
        return false;
      }
      if (e.type === "keydown" && e.ctrlKey && e.shiftKey && e.code === "KeyC") {
        if (term.hasSelection()) copy(term.getSelection());
        e.preventDefault();
        return false;
      }
      return true;
    });
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${scheme}://${location.host}/api/shells/${encodeURIComponent(name)}/attach`);
    ws.binaryType = "arraybuffer";
    const encoder = new TextEncoder();
    const sendSize = () => {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ rows: term.rows, cols: term.cols }));
    };
    ws.onopen = () => { setNote(""); sendSize(); toBody(); };
    // 004 FR-005 is tmux's work, not this page's. tmux attach draws on the terminal's alternate screen, which has no
    // scrollback here, so the view is always tmux's current screen: it opens at the end. With the mouse on (shells.py),
    // the wheel puts the pane in tmux copy mode, and copy mode keeps your place while output arrives; scrolling back
    // down to the end, or q, leaves it. So nothing here scrolls, and nothing should fight tmux for the wheel.
    ws.onmessage = (e) => term.write(new Uint8Array(e.data));
    ws.onclose = (e) => {
      setNote(e.code === 1000 || e.code === 1006 ? "Disconnected. The session keeps running; open it again to reattach." : `Closed: ${e.reason || e.code}`);
      if (e.code === 4404) onGone();
    };
    const typed = term.onData((d) => { if (ws.readyState === WebSocket.OPEN) ws.send(encoder.encode(d)); });
    const resized = term.onResize(sendSize);
    const observer = new ResizeObserver(() => fit.fit());
    observer.observe(box.current);
    return () => {
      observer.disconnect(); typed.dispose(); resized.dispose(); selected.dispose(); clearTimeout(hint);
      document.removeEventListener("focusout", followed); window.removeEventListener("focus", followed);
      ws.onclose = null; ws.close(); term.dispose();
    };
  }, [name]);
  // Keyed, or the note taking the first place would take over the terminal's element. The copy
  // message floats: anything that changes the terminal's height resizes the pane.
  return html`${note && html`<div key="note" class="small soft" style="padding: 6px 16px">${note}</div>`}
    <div key="term" class="term" ref=${box}></div>
    ${!typing && !quiet && html`<div key="unfocused" class="small term-copied" role="status">Keys aren't going to the terminal. Click it to type.</div>`}
    ${copied && html`<div key="copied" class="small term-copied" role="status">${copied}</div>`}`;
}

// --- sessions -------------------------------------------------------------------------------------
// Your own words to a Claude session (004 FR-008): through hubd as typed input, a turn of yours. Mid-turn they queue.
const MAX_MESSAGE = 4000;
let messageFields = 0;  // the Steward panel and Sessions can both show the Steward's field: each needs its own id
function MessageField({ name, where, off }) {
  const [text, setText] = useState("");
  const [note, setNote] = useState("");
  const act = useAct();
  const id = useMemo(() => `msg-${++messageFields}`, []);
  const send = () => act.run(async () => {
    setNote("");
    const r = await post("agents/say", { name, text, where });
    setText("");
    setNote(r.sent ? "Sent. It's your turn in the terminal." : `Queued (${r.queued} waiting). It goes when the turn ends, with the prompt empty.`);
  });
  const empty = !text.trim();
  return html`<div class="msgfield stack tight">
    <label class="eyebrow" for=${id}>Message to ${name}</label>
    <textarea id=${id} rows="2" maxlength=${MAX_MESSAGE} disabled=${!!off} placeholder="Type a message. Ctrl+Enter sends." value=${text}
      onInput=${(e) => setText(e.target.value)}
      onKeyDown=${(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && !empty && !act.busy) { e.preventDefault(); send(); } }}></textarea>
    <div class="row" style="gap: 8px; justify-content: space-between">
      <span role="status" class="small soft">${off || (act.busy ? "Sending…" : note)}</span>
      <span class="row" style="gap: 8px"><span class="small soft mono">${text.length > MAX_MESSAGE - 400 ? `${text.length} / ${MAX_MESSAGE}` : ""}</span>
        <button disabled=${!!off || empty || act.busy} onClick=${send}>Send</button></span></div>
    <${Err} text=${act.error} /></div>`;
}

// 004 FR-015: a plain shell, in a chosen repository's checkout or one of its session worktrees (or home).
function NewShell({ initial, groups, onDone, onCancel }) {
  const [name, setName] = useState(initial || "");
  const [repo, setRepo] = useState(null);
  const [cwd, setCwd] = useState("");
  const [command, setCommand] = useState("");
  const act = useAct();
  const places = useLoad(() => (repo ? post("agents/worktrees", { repo }).then((r) => r.worktrees) : Promise.resolve([])), [repo]);
  useEffect(() => { const first = (places.data || [])[0]; setCwd(first ? first.path : ""); }, [places.data]);
  return html`<div class="panel" style="padding: 14px; gap: 10px">
    <${Err} text=${act.error || places.error} />
    <label class="field"><span>Name</span><input value=${name} onInput=${(e) => setName(e.target.value)} /></label>
    <${RepoPicker} value=${repo} onChange=${(r) => { setRepo(r); if (!name.trim() && r) setName(`shell-${r.replace(/^\./, "")}`); }} groups=${groups} label="Repository" />
    ${repo && html`<label class="field"><span>Worktree</span><select value=${cwd} onChange=${(e) => setCwd(e.target.value)}>
      ${(places.data || []).map((w) => html`<option value=${w.path}>${w.label} · ${w.path}</option>`)}
      <option value="">home</option></select></label>
      ${places.data && !places.data.length && html`<span class="small soft">No checkout of ${repo} in the workspace yet: the shell starts in your home.</span>`}`}
    <label class="field"><span>Command</span><input placeholder="your shell" value=${command} onInput=${(e) => setCommand(e.target.value)} /></label>
    <div class="row"><button class="primary" disabled=${act.busy || !name.trim()} onClick=${async () => {
      const r = await act.run(() => post("shells", { name, cwd: cwd || null, command: command || null }));
      if (r) onDone(name);
    }}>Start</button><button onClick=${onCancel}>Cancel</button></div></div>`;
}

const shortModel = (m) => (m ? m[0].toUpperCase() + m.slice(1) : "");

// --- SessionView (004 FR-001–FR-011) --------------------------------------------------------------
// The state in words: the badge beside it is a second sign, never the only one.
function sessionWords(session) {
  const a = session.agent;
  if (!a) return session.attached > 0 ? "Attached" : "Plain shell";
  if (a.ended) return "Claude has ended";
  if (a.waiting) return "Waiting for you";
  return a.idle ? "Idle at its prompt" : "Working";
}
const byWords = (by) => (by === "you" ? "you" : by === STEWARD ? "the Steward" : by);
// 004 FR-002: where and why it was started, from its Launch record (005 FR-010).
function originWords(a) {
  const o = a.origin;
  if (!o && a.started_by) return `started by ${byWords(a.started_by)}`;
  if (!o) return a.origin_kept ? "started directly, not from Launch" : "started before origins were kept";
  const f = o.from || {};
  const where = !f.view ? "Launch" : f.ref ? `${f.view}${f.view === "Work" ? " item" : ","} ${f.ref}` : f.view;
  return `from ${where}${o.by ? `, by ${byWords(o.by)}` : ""}`;
}
const coversOf = (a) => (a ? (a.covers || []).map((c) => ({ kind: c.kind || a.object, repo: c.repo, number: c.number })) : []);

// 004 FR-009: what it was started with. Replaces the old manifest column.
function SessionSpec({ session, manifest: m, error }) {
  const a = session.agent;
  const [prompt, setPrompt] = useState(false);
  const attach = `tmux -L glassine-hub attach -t ${session.name}`;
  if (!a) {
    return html`<details class="svspec"><summary>Session spec</summary>
      <p class="small">A plain tmux shell as your user. No persona, no prompt; the tool server's URL and a token are in its environment, so a <code>claude</code> you start here can use the hub too.</p>
      <dl class="defs"><dt>Directory</dt><dd class="mono">${session.cwd}</dd><dt>Start command</dt><dd class="mono">${session.command}</dd><dt>Attach</dt><dd class="mono">${attach}</dd></dl></details>`;
  }
  const covers = coversOf(a);
  return html`<details class="svspec"><summary>Session spec</summary>
    <${Err} text=${error} />
    <dl class="defs">
      <dt>Persona</dt><dd>${a.persona_name || a.persona}${a.persona_name && a.persona_name !== a.persona ? html` <span class="mono soft">${a.persona}</span>` : ""}</dd>
      <dt>Action</dt><dd>${a.title} <span class="mono soft">${a.action}</span></dd>
      <dt>Model</dt><dd class="mono">${a.model} · ${a.effort}</dd>
      <dt>Permission mode</dt><dd class="mono">${a.permission_mode || "not recorded (started before it was kept)"}</dd>
      <dt>Ceiling</dt><dd>${m ? m.ceiling : "…"}</dd>
      <dt>Covered items</dt><dd>${covers.length ? html`<span class="row" style="gap: 6px">${covers.map((c) => html`<${ItemPill} ...${c} />`)}</span>` : "the whole project"}</dd>
      ${(m ? m.checkouts : []).map((c) => html`<dt>Worktree</dt><dd class="mono" style="overflow-wrap: anywhere">${c}</dd>`)}
      ${m && !m.checkouts.length && html`<dt>Worktree</dt><dd>none: it reads, with no checkout</dd>`}
      <dt>Branch</dt><dd class="mono">${m ? m.branch || "none" : "…"}</dd>
      <dt>Start command</dt><dd class="mono" style="overflow-wrap: anywhere">${m ? m.command : "…"}</dd>
      <dt>Posts as</dt><dd class="mono">${a.posts_as || "you"}</dd>
      <dt>Attach</dt><dd class="mono">${attach}</dd></dl>
    ${m && html`<div class="stack tight"><h3 class="eyebrow">Skills</h3><div class="row" style="gap: 6px">${m.skills.map((s) => html`<span class="badge" style="text-transform: none; letter-spacing: 0; font-size: 12.5px">${s}</span>`)}</div></div>
      <div class="stack" style="gap: 4px"><h3 class="eyebrow">Tools${a.full ? "" : ` · ${m.config.tools.length + m.config.hub_tools.length}`}</h3>
        ${a.full ? html`<p class="small">Full Claude Code, with your rights.</p>`
          : [...m.config.hub_tools, ...m.config.tools].map((t) => html`<div class="tool-row"><span class="mono" style="font-size: 13px">${t}</span><span class="badge">allow</span></div>`)}</div>
      <div class="row" style="gap: 8px">
        <button class="plain" aria-expanded=${prompt ? "true" : "false"} onClick=${() => setPrompt(!prompt)}>${prompt ? "Hide built prompt" : "Show built prompt"}</button>
        ${covers.length > 0 && html`<button class="plain" onClick=${() => launch({ action: a.action, covers, from: { view: "Sessions" } })}>Launch again on these items</button>`}</div>
      ${prompt && html`<pre class="shadow">${m.prompt}</pre>`}`}
  </details>`;
}

// One session, three places (004 FR-001): full under Sessions, embedded in a Work item, compact in the Steward panel.
// here: the Work item it's embedded in. seen: what the Steward sees, for its preset buttons.
// onView(mode): it was moved between embedded and background. onEnded(reply): Stop ended it. onResume: Claude ended, resume it.
function SessionView({ session, mode = "full", asks, here, seen, buttons, queued = 0, onView, onEnded, onResume, onGone, onClose, children }) {
  const a = session.agent;
  const name = session.name;
  const full = mode === "full", compact = mode === "compact";
  const act = useAct();
  const [confirm, dialog] = useConfirm();
  const [note, setNote] = useState("");
  const focus = useRef(null);
  const { data, error } = useLoad(() => (a && !compact ? post("agents/manifest", { name }) : Promise.resolve(null)), [name, a ? a.persona : ""]);
  const m = data && data.manifest;
  const mine = ((asks && asks.open) || []).filter((x) => x.session === name);
  const words = sessionWords(session);
  const covers = coversOf(a);
  const prs = a ? a.prs || [] : [];
  // 004 FR-004: the others, beside the one you're on.
  const others = here ? covers.filter((c) => `${c.repo}#${c.number}` !== here) : covers.slice(1);
  const hid = `sv-${mode}-${name}`;
  const where = full ? "Sessions" : compact ? (seen && seen.screen) || "Sessions" : "Work";
  const live = a && !a.ended;
  const thisItem = seen && seen.selection ? `${seen.kind || "item"} ${seen.selection}` : "";
  // The presets are written for the Steward (steward-buttons.toml). Other sessions get Esc and your own words.
  const offered = name === STEWARD && seen ? (buttons || []).filter((b) => b.screen === seen.screen && (seen.selection || !b.text.includes("{selection}")) && (!b.kinds || b.kinds.includes(seen.kind))) : [];
  const press = (b) => act.run(async () => {
    const r = await post("agents/press", { name, button: b.id, kind: seen.kind, selection: seen.selection });
    setNote(r.sent ? `Sent: ${b.label}` : `Queued: ${b.label}. It goes when the turn ends.`);
  });
  const place = (to) => act.run(async () => {
    await post("agents/view", { name, mode: to, where: to === "embedded" || !a.view || !a.view.where ? where : a.view.where, ref: here || (a.view && a.view.ref) || undefined });
    if (onView) onView(to);
  });
  const stop = () => confirm(
    { title: a ? "Stop this session?" : "End this shell?", danger: true, label: a ? "Stop session" : "End shell",
      text: a ? `Stops “${name}”: Claude and everything running in its terminal. Its conversation can be resumed later.` : `Ends “${name}” and everything running in it.` },
    () => act.run(async () => {
      const r = await api(`shells/${encodeURIComponent(name)}`, { method: "DELETE" });
      if (onEnded) onEnded(r);
    }),
  );
  const embeddedNow = mode === "embedded" || (a && a.view && a.view.mode === "embedded");
  const family = a && FAMILY_WORD[a.family] ? a.family : a ? "unknown" : "shell";
  const head = !compact && html`<header class="svhead ${family}">
    <${PersonaBadge} persona=${personaOf(a)} />
    <span class="stack" style="gap: 2px; flex: 1 1 220px; min-width: 0">
      <h2 id=${hid}>${a ? a.persona_name || a.persona : name}</h2>
      <span class="mono small" style="overflow-wrap: anywhere">${a ? html`${name} · ${shortModel(a.model)}${m && m.branch ? ` · ${m.branch}` : ""}` : session.cwd}</span>
      ${a && html`<span class="small">${originWords(a)}</span>`}</span>
    <span class="badge ${words === "Waiting for you" ? "mark" : a && a.ended ? "dim" : ""}">${words}</span>
    <span class="row" style="gap: 6px">
      ${a && embeddedNow && html`<button class="plain" disabled=${act.busy} onClick=${() => place("background")}>Send to background</button>`}
      ${!full && html`<a class="button plain" href=${hash("shells", { name })}>Open in Sessions</a>`}
      ${full && onClose && html`<button class="plain" onClick=${onClose}>Detach</button>`}
      <button class="plain" disabled=${act.busy} onClick=${stop}>${a ? "Stop…" : "End…"}</button></span></header>`;
  const pills = !compact && (covers.length > 0 || prs.length > 0) && html`<div class="svitems">
    ${covers.length > 0 && html`<span class="row" style="gap: 6px"><span class="eyebrow">Covers</span><${ItemPill} ...${here ? covers.find((c) => `${c.repo}#${c.number}` === here) || covers[0] : covers[0]} /></span>`}
    ${others.length > 0 && html`<nav class="row" style="gap: 6px" aria-label="Also on these items"><span class="eyebrow">Also on these items</span>${others.map((c) => html`<${ItemPill} ...${c} />`)}</nav>`}
    ${prs.length > 0 && html`<span class="row" style="gap: 6px"><span class="eyebrow">Pull requests</span>${prs.map((p) => html`<${ItemPill} kind="pr" repo=${p.repo} number=${p.number} state=${p.state ? String(p.state).toLowerCase() : undefined} />`)}</span>`}</div>`;
  return html`${dialog}<section class="sv ${mode} ${full ? "termbox" : mode === "embedded" ? "embedded" : "dock-session"}" aria-labelledby=${compact ? undefined : hid} aria-label=${compact ? `Session ${name}` : undefined}>
    ${head}${pills}
    ${!compact && html`<${SessionSpec} session=${session} manifest=${m} error=${error} />`}
    <${Err} text=${act.error} />
    ${mine.length > 0 && html`<div class="${compact ? "dock-asks" : "session-asks"} stack" style="gap: ${compact ? 8 : 10}px">${mine.map((x) => html`<${Ask} key=${x.id} ask=${x} compact=${compact} onDone=${asks.reload} />`)}</div>`}
    ${children}
    ${a && a.waiting && !mine.length && !compact && html`<div role="status" class="waitbar"><span>Waiting for you: answer in the terminal below.</span>
      <button class="plain" onClick=${() => focus.current && focus.current()}>Jump to prompt</button></div>`}
    ${a && a.ended && onResume && html`<div role="status" class="waitbar ended"><span>Claude has ended in this session.</span>
      <button class="plain" disabled=${act.busy} onClick=${onResume}>Resume…</button></div>`}
    <div class=${compact ? "dock-term" : "svterm"}><${TerminalView} key=${name} name=${name} quiet=${compact} focusRef=${focus} onGone=${onGone || (() => {})} /></div>
    ${a && html`<div class="svsend ${compact ? "compact" : ""}">
      <div class="row" style="gap: 6px">
        ${offered.map((b) => html`<button class="dock-msg" disabled=${act.busy || !live} title=${b.text.replaceAll("{selection}", thisItem)} onClick=${() => press(b)}>${b.label}</button>`)}
        <button class="dock-msg" title="Stops the turn, and anything queued for after it" disabled=${act.busy || !live} onClick=${() => act.run(async () => { await post("agents/interrupt", { name }); setNote("Sent Esc."); })}>Esc</button>
        <span role="status" class="small soft">${queued > 0 ? `${count(queued, "message")} queued until the turn ends, with the prompt empty. If it has ended, clear what's typed there. After Esc in the terminal, press Esc here too.` : note.startsWith("Queued") ? "" : note}</span></div>
      <${MessageField} key=${name} name=${name} where=${where} off=${a.ended ? "Claude has ended in this session: resume it to write to it." : ""} /></div>`}
  </section>`;
}

const hubTool = (tool) => tool.replace(/^mcp__glassine-hub__/, "hub.");
const TOOL_TITLES = { Bash: "Run a command", Edit: "Edit a file", Write: "Write a file", WebFetch: "Fetch a page", WebSearch: "Search the web", ExitPlanMode: "Approve the plan" };
const RECOMMENDED = " (Recommended)";
const clock = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
const waitedWords = (s) => (s < 90 ? `${s} s` : `${Math.round(s / 60)} min`);
const toolTitle = (tool) => {
  const mcp = tool.match(/^mcp__(.+?)__(.+)$/);
  return TOOL_TITLES[tool] || (mcp ? `Use ${mcp[2]} from ${mcp[1]}` : `Use ${tool}`);
};
const shownLabel = (label) => (label.endsWith(RECOMMENDED) ? label.slice(0, -RECOMMENDED.length) : label);

function askLines(text, sign) {
  return (text || "").split("\n").map((line) => ({ sign, line }));
}

// What each tool's own view shows. Anything else in its input goes under it: Allow approves all of it.
const MESSAGE_TOOL = "mcp__glassine-hub__message_session";
const TOOL_VIEWS = { Bash: ["command", "description"], Edit: ["file_path", "old_string", "new_string"], Write: ["file_path", "content"], ExitPlanMode: ["plan"], [MESSAGE_TOOL]: ["text", "name"] };
const hasView = (tool, input) => tool in TOOL_VIEWS && typeof input[TOOL_VIEWS[tool][0]] === "string"
  && TOOL_VIEWS[tool].every((k) => input[k] === undefined || typeof input[k] === "string");

// All of what the tool would do, from its real input. Claude's own description goes under "why".
function AskContent({ ask }) {
  const input = ask.input;
  if (ask.too_long) return html`<p class="small">This is too long to show on a card, so it can only be allowed in the terminal.</p>`;
  if (!hasView(ask.tool, input)) return html`<pre class="ask-code">${JSON.stringify(input, null, 2)}</pre>`;
  const rest = Object.fromEntries(Object.entries(input).filter(([k]) => !TOOL_VIEWS[ask.tool].includes(k)));
  return html`<${AskView} ask=${ask} />${Object.keys(rest).length > 0 && html`<div class="stack" style="gap: 4px"><${Eyebrow} soft>Also set<//><pre class="ask-code">${JSON.stringify(rest, null, 2)}</pre></div>`}`;
}

function AskView({ ask }) {
  const input = ask.input;
  if (ask.tool === MESSAGE_TOOL) return html`<div class="stack" style="gap: 4px"><span class="small">To <span class="mono">${input.name}</span>, as its next turn:</span><pre class="ask-code" style="white-space: pre-wrap">${input.text}</pre></div>`;
  if (ask.tool === "Bash") return html`<pre class="ask-code"><span class="ask-prompt">$ </span>${input.command}</pre>`;
  if (ask.tool === "Edit" || ask.tool === "Write") {
    const lines = ask.tool === "Write" ? askLines(input.content, "+") : [...askLines(input.old_string, "−"), ...askLines(input.new_string, "+")];
    return html`<div class="ask-diff"><span class="ask-path">${input.file_path}</span>
      <div class="ask-lines">${lines.map((l) => html`<span class=${l.sign === "+" ? "add" : "del"}>${l.sign} ${l.line}</span>`)}</div></div>`;
  }
  return html`<div class="ask-plan"><${Md} text=${input.plan} /></div>`;
}

function askResult(ask) {
  const said = ask.said;
  if (ask.state === "allowed") return ["Allowed from hub · the prompt closed and the tool ran.", "check", ""];
  if (ask.state === "always") return [`Allowed · it won't ask again for ${said} in this session.`, "check", ""];
  if (ask.state === "denied") return [`Denied · Claude was told: “${said}”. The tool doesn't run, unless the terminal had already said yes.`, "cross", "bad"];
  if (ask.state === "terminal") return [ask.terminal ? "Answered in the terminal · this card closed itself." : "Cancelled in the terminal · this card closed itself.", "check", ""];
  if (ask.state === "stopped") return ["The session stopped, so this closed with it.", "clock", "dim"];
  if (ask.state === "timeout" && !ask.terminal) return [`Hub stopped waiting after ${Math.round(ask.wait / 60)} min, so it was refused. Claude goes on without your answer.`, "clock", "dim"];
  if (ask.state === "timeout") return [`Hub stopped waiting after ${Math.round(ask.wait / 60)} min. Nothing was approved from here. Unless the terminal has answered, its prompt is still open.`, "clock", "dim"];
  const words = Object.entries(said || {});
  return [`Answered · Claude saw ${words.map(([, a]) => `“${a}”`).join(", ")}.`, "check", ""];
}

function AskQuestion({ q, value, onChange, steward }) {
  const multi = !!q.multiSelect;
  const on = (label) => (multi ? value.picked.includes(label) : value.picked[0] === label);
  const pick = (label) => onChange({ ...value, other: multi && value.other, picked: multi ? (on(label) ? value.picked.filter((x) => x !== label) : [...value.picked, label]) : [label] });
  const toggleOther = () => (multi ? onChange({ ...value, other: !value.other }) : onChange({ ...value, picked: [], other: true }));
  return html`<div class="stack" style="gap: 10px">
    ${q.header && html`<${Eyebrow} soft>${q.header}<//>`}
    <h3 class="ask-question">${q.question}</h3>
    <div role=${multi ? "group" : "radiogroup"} aria-label=${q.question} class="stack" style="gap: 8px">
      ${(q.options || []).map((o) => html`<button type="button" role=${multi ? "checkbox" : "radio"} aria-checked=${on(o.label) ? "true" : "false"} class="ask-option" onClick=${() => pick(o.label)}>
        <span class="ask-dot ${multi ? "square" : ""}" aria-hidden="true"></span>
        <span class="stack" style="gap: 2px; flex: 1; min-width: 0">
          <span class="row" style="gap: 4px 8px"><b style="font-weight: 600">${shownLabel(o.label)}</b>${o.label.endsWith(RECOMMENDED) && html`<span class="ask-rec">${steward ? "STEWARD'S PICK" : "SUGGESTED"}</span>`}</span>
          ${o.description && html`<span class="small soft">${o.description}</span>`}</span></button>`)}
      <div class="ask-other ${value.other ? "on" : ""}">
        <button type="button" role=${multi ? "checkbox" : "radio"} aria-checked=${value.other ? "true" : "false"} class="ask-other-pick" onClick=${toggleOther}>
          <span class="ask-dot ${multi ? "square" : ""}" aria-hidden="true"></span>Something else</button>
        ${value.other && html`<label class="ask-other-text"><span class="sr">Your answer</span>
          <input type="text" value=${value.text} placeholder="Type your answer" onInput=${(e) => onChange({ ...value, text: e.target.value })} /></label>`}</div></div></div>`;
}

// --- new work: a planner, then a session that ends in drafts, which nothing files until you choose ---------------
// --- Launch (005): brief, planning, plan, run, result ------------------------------------------------
// Opens over any view. detail: { id?: a record (a suggestion, or one you reopen), action?, covers?: [{kind, repo, number}],
// repos?: [repo], from: {view, ref?} (where it was opened, 005 FR-001/FR-010), notes?, pins?, context?, steward?: drafted with the Steward }.
const launch = (detail = {}) => window.dispatchEvent(new CustomEvent("hub-launch", { detail }));
const NW_TEXT = {
  "new-issue": { label: "What’s wrong or wanted", hold: "e.g. pen lag doubles when battery saver is on", hint: "e.g. check whether it’s a duplicate first", },
  "new-security-audit": { hint: "e.g. assume any local user can reach the socket", },
  "new-architecture-audit": { hint: "e.g. focus on how two parts share state", },
  "new-roadmap-item": { label: "What should exist, and why", hold: "e.g. read the docs offline on the device", hint: "e.g. keep it out of the next release", },
  "new-docs-sweep": { hint: "e.g. only things shipped in the last release", },
  "new-dependency-review": { hint: "e.g. no major upgrades for now", },
};
const NW_MODEL = { fable: "Fable", opus: "Opus", sonnet: "Sonnet", haiku: "Haiku" };
const NW_WAITING = ["offered", "planned", "done", "failed"];
// hubd refuses anything else. Haiku is its default, and what a planner run costs least on.
const PLANNER_CHOICES = ["haiku", "sonnet", "opus"];
const PLANNER_DEFAULT = "haiku";
const nwWaits = (item) => NW_WAITING.includes(item.state);
// 005 FR-002, in this order. failed and dismissed are where a Launch stopped, shown on the stage it stopped at.
const LAUNCH_STAGES = [["brief", "Brief"], ["planning", "Planning"], ["plan", "Plan"], ["run", "Run"], ["result", "Result"]];
const OBJECT_WORDS = { issue: "an issue", pr: "a pull request", run: "a run", repo: "a repository" };
const MAX_COVERS = 6; // hubd's: one item and five more
const coverOf = (c) => ({ kind: c.kind, repo: c.repo, number: c.number });
// A record from before covers were kept names its items by number.
const recordCovers = (r, object) => (r.covers && r.covers.length ? r.covers.map(coverOf)
  : r.number ? [r.number, ...(r.also_numbers || [])].map((n) => ({ kind: object || "issue", repo: r.repo, number: n })) : []);
// 005 FR-011, before planning: hubd says the same and refuses.
function launchRefusal(action, covers) {
  if (!action) return null;
  if (action.object === "repo") return covers.length ? `${action.title} works on a repository, not on an item like ${ref(covers[0])}. Remove the items, or choose another action.` : null;
  const other = covers.find((c) => c.kind !== action.object);
  if (other) return `${action.title} works on ${OBJECT_WORDS[action.object]}, and ${ref(other)} is ${OBJECT_WORDS[other.kind]}, so it can't start there.`;
  return covers.length ? null : `${action.title} works on ${OBJECT_WORDS[action.object]}: add one below.`;
}

const PlannerModel = ({ value, onChange, id }) => html`<div class="stack" style="gap: 6px"><span id=${id} class="eyebrow">Planner</span>
  <div role="radiogroup" aria-labelledby=${id} class="seg">${PLANNER_CHOICES.map((m) => html`<button role="radio" aria-checked=${value === m ? "true" : "false"} onClick=${() => onChange(m)}>${NW_MODEL[m]}</button>`)}</div></div>`;

// Every action there is to launch: the item kinds' and new work on a repository (with the form's extra fields).
function useLaunchActions(templates) {
  const { data, error } = useLoad(() => Promise.all([api(`agents/actions${params({ object: "repo" })}`), api("agents/actions")]), []);
  const extra = new Map((templates || []).map((t) => [t.id, t]));
  const list = data ? [...data[0], ...data[1]].filter((a) => a.object !== "project").map((a) => ({ ...a, ...(extra.get(a.id) ? { asks_describe: extra.get(a.id).asks_describe, asks_paths: extra.get(a.id).asks_paths, repo: extra.get(a.id).repo } : {}) })) : null;
  return { list, error };
}

// The stage bar (005 FR-002): every stage named, the current one marked.
function LaunchStages({ stage, stopped }) {
  const at = LAUNCH_STAGES.findIndex(([s]) => s === stage);
  return html`<nav class="nw-rail" aria-label="Launch stages"><ol>
    ${LAUNCH_STAGES.map(([s, name], i) => html`<li><div class="nw-step" aria-current=${i === at ? "step" : null}>
      <span class="nw-n ${i < at ? "done" : ""}" aria-hidden="true">${i < at ? "✓" : i + 1}</span>
      <span class="stack" style="gap: 0; min-width: 0"><b>${name}</b><span class="small soft">${i === at ? (stopped || "now") : i < at ? "done" : ""}</span></span></div></li>`)}</ol>
    <p class="small soft nw-railnote">Brief and plan are cheap and change nothing. The session in Run is where the time goes, and it keeps running if you close this.</p></nav>`;
}

// The draft issues a drafts result hands in (005 FR-015): file as they are, edit and file on GitHub, or send to the Steward.
function DraftsResult({ item, reload, onNote }) {
  const [picked, setPicked] = useState({});
  const [editing, setEditing] = useState(null); // {index, title, body}
  const act = useAct(reload);
  const { data: overview, error: overviewError } = useLoad(() => api("overview"), [], 20000);
  const drafts = item.drafts || [];
  const chosen = drafts.flatMap((d, i) => (d.state === "draft" && picked[i] === true ? [i] : []));  // yours to read first: nothing starts out chosen
  const left = drafts.filter((d) => d.state === "draft").length;
  // true, false, or null when it isn't known: never read as private.
  const isPublic = (name) => { const r = overview ? overview.groups.flatMap((g) => g.repos).find((x) => x.name === name) : null; return r ? !r.private : null; };
  const targets = [...new Set(chosen.map((i) => drafts[i].target))];
  const publicCount = chosen.filter((i) => isPublic(drafts[i].target) === true).length;
  const unknown = targets.filter((t) => isPublic(t) === null);
  const fileLabel = `File ${chosen.length} in ${targets.join(", ")}${publicCount ? ` (${publicCount} public)` : ""}`;
  const file = () => act.run(async () => {
    const r = await post(`new-work/${item.id}/file`, { indexes: chosen });
    onNote(`${count(chosen.length - r.errors.length, "issue")} filed${r.errors.length ? `, ${r.errors.length} not` : ""}${r.warnings.length ? `, ${r.warnings.length} not on the board` : ""}${r.errors.length || r.warnings.length ? ": see the draft." : "."}`);
  });
  const hand = () => act.run(async () => {
    await post(`new-work/${item.id}/hand`, { indexes: chosen });
    onNote(`${count(chosen.length, "draft")} with the Steward. Each issue it files asks you first.`);
  });
  const steward = item.driver === "steward";
  const save = () => act.run(async () => {
    await post(`new-work/${item.id}/edit`, { index: editing.index, title: editing.title, body: editing.body });
    setEditing(null);
  });
  return html`<div class="stack" style="gap: 10px">
    <div class="row" style="gap: 6px 12px; align-items: baseline"><h3>Drafts</h3><span class="small soft" style="flex: 1">${item.session ? `from ${item.session} · ` : ""}Nothing is filed until you choose.</span><span class="mono small">${chosen.length} of ${left} selected</span></div>
    ${drafts.map((d, i) => {
      const on = d.state === "draft" && picked[i] === true;
      return html`<div class="nw-draft ${on ? "on" : ""}" key=${i}>
        ${d.state === "draft" && html`<input type="checkbox" aria-label=${`Select draft: ${d.title}`} checked=${on} onChange=${() => setPicked({ ...picked, [i]: !on })} />`}
        <div class="stack" style="gap: 4px; flex: 1; min-width: 0">
          <div class="row" style="gap: 6px 10px">
            ${d.severity && html`<span class="nw-sev ${d.severity}">${d.severity.toUpperCase()}</span>`}
            <strong>${d.title}</strong>
            ${d.state === "filed" && html`<a class="nw-tag" href=${d.url} target="_blank" rel="noreferrer">FILED</a>`}
            ${d.state === "handed" && html`<span class="nw-tag">WITH THE STEWARD</span>`}
            ${d.state === "filing" && html`<span class="nw-tag">FILING…</span>`}</div>
          ${editing && editing.index === i ? html`<div class="stack" style="gap: 6px">
              <label class="nw-field">Title<input maxlength="200" value=${editing.title} onInput=${(e) => setEditing({ ...editing, title: e.target.value })} /></label>
              <label class="nw-field">Body<textarea rows="8" maxlength="8000" value=${editing.body} onInput=${(e) => setEditing({ ...editing, body: e.target.value })} /></label>
              <div class="row"><button class="primary" disabled=${act.busy || !editing.title.trim()} onClick=${save}>Save the draft</button><button class="plain" onClick=${() => setEditing(null)}>Cancel</button></div></div>`
            : d.body ? html`<div class="small nw-draft-body"><${Md} text=${d.body} showUrls=${true} /></div>` : html`<span class="small soft">No body</span>`}
          ${d.state === "draft" && item.state === "done" && !(editing && editing.index === i) && html`<button class="plain" style="align-self: flex-start" onClick=${() => setEditing({ index: i, title: d.title, body: d.body })}>Edit before filing</button>`}
          ${/!\[|<img|<\/?(?:picture|source|video|audio)\b/i.test(d.body) && html`<span class="small" role="alert">Has an image or media link: filing it can make GitHub fetch that address. Check it above.</span>`}
          <span class="small">→ <span class="mono">GlassineOS/${d.target}</span>${isPublic(d.target) === true && html` <span class="nw-tag">PUBLIC</span>`}${isPublic(d.target) === null && html` <span class="nw-tag">PUBLIC OR PRIVATE: NOT KNOWN YET</span>`}${d.labels.length > 0 && html` · <span class="mono">${d.labels.join(", ")}</span>`}${d.parent && html` · parent <span class="mono">${d.parent}</span>`}</span>
          ${d.note && html`<span class="small" role="alert">${d.note}</span>`}</div></div>`;
    })}
    ${unknown.length > 0 && html`<p class="small" role="status">Filing waits: can't tell whether ${unknown.join(", ")} is public${overviewError ? ` (${overviewError})` : ""}. Trying again.</p>`}
    <${Err} text=${act.error} />
    ${item.state === "done" && left > 0 && html`<div class="row">
      <button class=${steward ? "plain" : "primary"} disabled=${act.busy || !chosen.length || unknown.length > 0} onClick=${file}>${chosen.length ? fileLabel : "Choose drafts to file"}</button>
      <button class=${steward ? "primary" : "plain"} disabled=${act.busy || !chosen.length} onClick=${hand}>${steward ? `Send ${chosen.length} to the Steward` : "Send to the Steward instead"}</button>
</div>`}
  </div>`;
}

// 005 FR-016–FR-020 and 003 FR-010: one view per result type, in Launch and on its card in Needs you. The text is the
// session's, which may have read an outsider's: shown as text, never rendered, links printed in full.
const RESULT_TITLE = { comment: "Review to post", labels: "Labels to apply", findings: "Findings", report: "Report", pr: "Pull request" };
const resultTitle = (r) => `${RESULT_TITLE[r.type] || "Result"}${r.items && r.items[0] ? ` · ${ref(r.items[0])}` : ""}`;
const EVENT_WORD = { comment: "Comment", "request-changes": "Request changes", approve: "Approve" };
const plainText = (t, mono) => html`<p class="small ${mono ? "mono" : ""}" style="white-space: pre-wrap; overflow-wrap: anywhere">${t}</p>`;
const refItem = (text, kind) => { const m = /^([A-Za-z0-9._-]+)#(\d+)$/.exec(text || ""); return m ? { kind, repo: m[1], number: Number(m[2]) } : null; };

function PrResultTitle({ repo, number }) {
  const { data } = useLoad(() => api(`prs/${repo}/${number}`).catch(() => null), [repo, number]);
  return html`<${ItemPill} kind="pr" repo=${repo} number=${number} title=${data ? data.title : undefined} href=${hash("work", { tab: "prs", at: repo, item: number })} />`;
}

function ResultView({ r, reload, where = "Needs you" }) {
  const act = useAct(reload);
  const p = r.payload || {};
  const waits = r.state === "pending" && !r.kept;
  const answer = (verdict, extra = {}) => act.run(() => answerAt(r.id, { verdict, ...extra }, where));
  const setAside = waits && html`<button class="plain" disabled=${act.busy} onClick=${() => answer("dismiss")}>Set aside</button>`;
  let body = null;
  if (r.type === "comment") {
    body = html`<span class="eyebrow">${EVENT_WORD[p.event] || "Comment"} · summary</span>${plainText(p.summary)}
      ${(p.notes || []).length > 0 && html`<span class="eyebrow">Inline notes · ${p.notes.length}</span>
        <ul class="stack" style="gap: 6px">${p.notes.map((n) => html`<li class="stack tight"><span class="mono small">${n.path}:${n.line}${n.side === "LEFT" ? " (old side)" : ""}</span>${plainText(n.body)}</li>`)}</ul>`}
      ${waits && html`<div class="row"><button class="primary" disabled=${act.busy} onClick=${() => answer("apply")}>Post</button>${setAside}
        <span class="small soft">Posts one review on the pull request${r.persona ? `, as ${r.persona}'s App` : ""}.</span></div>`}`;
  } else if (r.type === "labels") {
    body = html`<ul class="stack" style="gap: 10px">${(p.issues || []).map((i, n) => {
      const item = refItem(i.ref, "issue");
      return html`<li class="stack tight">${item ? html`<${ItemPill} ...${item} />` : html`<span class="mono small">${i.ref}</span>`}
        <span class="row" style="gap: 6px">${i.add.map((l) => html`<span class="label">+ ${l}</span>`)}${i.remove.map((l) => html`<span class="label">− ${l}</span>`)}</span>
        ${i.part_of && html`<span class="small">Part of <span class="mono">${i.part_of}</span></span>`}
        ${i.why && plainText(i.why)}
        ${waits && (p.issues || []).length > 1 && html`<button class="plain" style="align-self: flex-start" disabled=${act.busy} onClick=${() => answer("apply", { indexes: [n] })}>Apply to ${i.ref}</button>`}</li>`;
    })}</ul>
      ${waits && html`<div class="row"><button class="primary" disabled=${act.busy} onClick=${() => answer("apply")}>Apply</button>${setAside}</div>`}`;
  } else if (r.type === "findings") {
    const notes = `Findings${r.items && r.items[0] ? ` on ${ref(r.items[0])}` : ""}, from ${r.session}:\nCause: ${p.cause}\nSmallest fix: ${p.fix}`.slice(0, 4000);
    body = html`<span class="eyebrow">Cause</span>${plainText(p.cause)}<span class="eyebrow">Smallest fix</span>${plainText(p.fix)}
      ${(p.files || []).length > 0 && html`<span class="eyebrow">Files</span>${plainText(p.files.join("\n"), true)}`}
      <div class="row"><button class="primary" onClick=${() => launch({ verb: "fix", notes, from: { view: where } })}>Start a fix session</button>${setAside}</div>`;
  } else if (r.type === "report") {
    body = html`${p.question && html`<span class="eyebrow">Question</span>${plainText(p.question)}`}<span class="eyebrow">Answer</span>${plainText(p.answer)}
      ${(p.unsettled || []).length > 0 && html`<span class="eyebrow">Couldn't settle</span><ul>${p.unsettled.map((t) => html`<li>${plainText(t)}</li>`)}</ul>`}
      ${(p.sources || []).length > 0 && html`<span class="eyebrow">Sources</span><ul class="stack" style="gap: 4px">${p.sources.map((s) => html`<li>${plainText(`${s.link} — ${s.why}`)}</li>`)}</ul>`}
      ${(p.followups || []).length > 0 && html`<span class="eyebrow">Follow-ups</span><ul>${p.followups.map((t) => html`<li>${plainText(t)}</li>`)}</ul>`}
      ${r.kept ? html`<p class="small" role="status">Saved to Knowledge.</p>` : waits && html`<div class="row"><button class="primary" disabled=${act.busy} onClick=${() => answer("keep")}>Save to Knowledge</button>${setAside}</div>`}`;
  } else if (r.type === "pr") {
    const closes = (r.items || []).filter((i) => i.kind === "issue");
    body = html`<${PrResultTitle} repo=${p.repo} number=${p.number} />
      ${closes.length > 0 && html`<span class="mono small" style="white-space: pre-line">${closes.map((i) => `Closes ${ref(i)}`).join("\n")}</span>`}
      <div class="row"><a class="button" href=${hash("work", { tab: "prs", at: p.repo, item: p.number })}>Open the pull request</a>${setAside}</div>`;
  }
  return html`<div class="ask calm ${r.session === STEWARD ? "steward" : ""} ${waits ? "" : "done"}">
    <div class="ask-head"><span class="ask-kind">${r.state === "applying" ? "APPLYING" : waits ? "RESULT READY" : "RESULT"}</span><span class="small mono">${r.session}</span></div>
    <div class="ask-body stack" style="gap: 8px"><div class="ask-title">${resultTitle(r)}</div>${body}
      ${r.note && html`<p class="small" role="status">${r.note}</p>`}<${Err} text=${act.error} /></div></div>`;
}

// The brief (005 FR-003, FR-004): what the planner reads. A suggestion's notes are marked as the suggester's.
function LaunchBrief({ seed, actions, templates, groups, onPlanned, onCancel, busyId }) {
  const steward = seed.by === STEWARD || seed.steward;
  const suggester = seed.by && seed.by !== "you" ? (seed.by === STEWARD ? "the Steward" : seed.by) : null;
  const initial = actions.find((a) => a.id === seed.action) || (seed.verb && actions.find((a) => a.verb === seed.verb))
    || (seed.covers && seed.covers[0] && actions.find((a) => a.object === seed.covers[0].kind && a.verb))
    || actions.find((a) => a.object === "repo") || actions[0];
  const [actionId, setActionId] = useState(initial && initial.id);
  const action = actions.find((a) => a.id === actionId) || initial;
  const [covers, setCovers] = useState(() => recordCovers(seed, initial && initial.object).slice(0, MAX_COVERS));
  const [repo, setRepo] = useState((seed.repos && seed.repos[0]) || seed.repo || (covers[0] && covers[0].repo) || null);
  const [describe, setDescribe] = useState(seed.describe || "");
  const [paths, setPaths] = useState(seed.paths || "");
  const [notes, setNotes] = useState(seed.notes || "");
  const [pins, setPins] = useState(seed.pins || []);
  const [model, setModel] = useState(seed.model || null);
  const [plannerModel, setPlannerModel] = useState(seed.planner_model || PLANNER_DEFAULT);
  const [driver, setDriver] = useState(seed.driver || (steward ? "steward" : "you"));
  const act = useAct();
  if (!action) return html`<div class="nw-body"><p>No actions are set up on this hub.</p></div>`;
  const onItems = action.object !== "repo";
  const chosenRepo = action.repo || repo;
  const refusal = launchRefusal(action, covers);
  const verbs = actions.filter((a) => a.verb);
  const more = actions.filter((a) => !a.verb && (!covers.length || a.object === covers[0].kind));
  const text = NW_TEXT[action.id] || {};
  const allRepos = groups.flatMap((g) => g.repos.map((r) => r.name));
  const chosenModel = model && action.models.includes(model) ? model : action.models[0];
  const plan = () => act.run(async () => {
    const r = await post("new-work", { id: busyId || null, action: action.id, covers: onItems ? covers : null, repos: onItems ? null : chosenRepo ? [chosenRepo] : [],
      describe: action.asks_describe ? describe : "", paths: action.asks_paths ? paths : "", notes, pins, model: chosenModel, driver,
      why: seed.why || "", context: seed.context || "", planner_model: plannerModel, from: seed.from || null });
    onPlanned(r.work);
  });
  return html`<div class="nw-body">
    ${seed.why && html`<div class="nw-why"><span class="nw-why-word">why</span><span>${seed.why}</span></div>`}
    <div class="stack" style="gap: 6px"><span id="lb-action" class="eyebrow">Action</span>
      <div role="radiogroup" aria-labelledby="lb-action" class="row" style="gap: 6px">${verbs.map((a) => html`<button role="radio" class="pill" aria-checked=${a.id === action.id ? "true" : "false"} title=${a.title} onClick=${() => setActionId(a.id)}>${a.verb}</button>`)}</div>
      ${more.length > 0 && html`<label class="field" style="align-self: flex-start"><span>More…</span>
        <select value=${action.verb ? "" : action.id} onChange=${(e) => e.target.value && setActionId(e.target.value)}><option value="">${action.verb ? "Other actions" : action.title}</option>
          ${more.map((a) => html`<option value=${a.id}>${a.title}</option>`)}</select></label>`}</div>
    <div class="row" style="gap: 10px 14px; align-items: flex-start">
      <${PersonaBadge} persona=${{ id: action.persona, name: action.persona_name, initials: action.initials, family: action.family }} hidden />
      <div class="stack tight" style="flex: 1 1 260px; min-width: 0"><b>${action.title} · ${action.persona_name}</b>
        <span class="small soft">${action.summary}</span>
        <span class="small nw-ceiling">${(action.result_words || "").replace(/^./, (c) => c.toUpperCase())}. ${action.ceiling}</span></div></div>
    ${onItems ? html`<div class="stack" style="gap: 6px"><span class="eyebrow">Covers · ${covers.length || "none yet"}</span>
        ${covers.length > 0 && html`<div class="row" style="gap: 6px">${covers.map((c, i) => html`<${ItemPill} key=${ref(c)} ...${c} removable onRemove=${() => setCovers(covers.filter((_, j) => j !== i))} />`)}</div>`}
        ${covers.length < MAX_COVERS && html`<${ItemPicker} repos=${allRepos} kind=${action.object} many label=${`Add ${OBJECT_WORDS[action.object]}`}
          exclude=${covers.map(ref)} onPick=${(item) => setCovers((now) => (now.some((c) => ref(c) === ref(item)) || now.length >= MAX_COVERS ? now : [...now, coverOf({ ...item, kind: item.kind || action.object })]))} />`}
        ${covers.length > 1 && html`<span class="small soft">The session's checkout is in ${covers[0].repo}, the first item's repository; the others are listed as covered.</span>`}</div>`
      : action.repo ? html`<div class="small"><${Eyebrow}>In<//> <span class="mono">GlassineOS/${action.repo}</span> · org board</div>`
      : html`<${RepoPicker} value=${repo} onChange=${setRepo} groups=${groups} label="Repository" />`}
    ${launchRefusal(action, covers) && html`<p class="small" role="alert">${refusal}</p>`}
    ${action.asks_paths && html`<label class="nw-field">Scope <span class="nw-sub">optional · paths in the repository</span>
      <input class="mono" value=${paths} placeholder="the whole repository" onInput=${(e) => setPaths(e.target.value)} /></label>`}
    ${action.asks_describe && html`<label class="nw-field">${text.label || "What to plan"}
      <textarea rows="3" placeholder=${text.hold || ""} value=${describe} onInput=${(e) => setDescribe(e.target.value)} /></label>`}
    ${suggester && html`<p class="small"><span class="nw-tag">${suggester === "the Steward" ? "STEWARD" : "SUGGESTED"}</span> ${suggester} wrote the notes below; edit freely.</p>`}
    <${SteerFields} kind=${action.object} notes=${notes} pins=${pins} onNotes=${setNotes} onPins=${setPins} />
    <div class="row" style="gap: 14px 24px; align-items: flex-start">
      <div class="stack" style="gap: 6px"><span id="lb-model" class="eyebrow">Model</span>
        <div role="radiogroup" aria-labelledby="lb-model" class="seg">${action.models.map((m, i) => html`<button role="radio" aria-checked=${chosenModel === m ? "true" : "false"} onClick=${() => setModel(m)}>${NW_MODEL[m] || m}${i === 0 ? " · default" : ""}</button>`)}</div></div>
      ${action.plan !== false && html`<${PlannerModel} id="lb-pm" value=${plannerModel} onChange=${setPlannerModel} />`}
      ${action.result === "drafts" && html`<div class="stack" style="gap: 6px"><span id="lb-drv" class="eyebrow">Drafts go to</span>
        <div role="radiogroup" aria-labelledby="lb-drv" class="seg">
          <button role="radio" aria-checked=${driver === "you" ? "true" : "false"} onClick=${() => setDriver("you")}>Me</button>
          <button role="radio" aria-checked=${driver === "steward" ? "true" : "false"} onClick=${() => setDriver("steward")}>The Steward, to refine</button></div></div>`}</div>
    <${Err} text=${act.error} />
    <div class="row">
      <button class="primary" disabled=${act.busy || Boolean(refusal) || (!onItems && !chosenRepo) || (action.asks_describe && !describe.trim())}
        title=${refusal || (!onItems && !chosenRepo ? "Choose a repository first" : "")} onClick=${plan}>${action.plan === false ? "Next: nothing to plan" : "Plan"}</button>
      <span class="small soft" style="flex: 1 1 220px">${action.plan === false ? "This action has no planner: its plan is the action's own." : `The planner (${NW_MODEL[plannerModel]}) reads first, read-only. Nothing runs until you've read its plan.`}</span>
      ${onCancel && html`<button class="plain" onClick=${onCancel}>Back to the plan</button>`}</div>
  </div>`;
}

// The plan (005 FR-006): the steps and what each touches, the briefing, the docs. Start, or edit the brief and plan again.
function LaunchPlan({ live, action, act, onEdit, onStart }) {
  const spec = live.spec || {};
  const steps = (live.plan && live.plan.steps) || [];
  // Yours if you chose one on the brief, else the planner's pick.
  const yours = action && live.model && live.model !== action.models[0];
  const pick = !yours && action && action.models.includes(live.planner_pick) ? live.planner_pick : live.model;
  const [model, setModel] = useState(null);
  const [brief, setBrief] = useState(null);
  const chosen = model || pick;
  const shownBrief = brief === null ? spec.brief || "" : brief;
  const plannerName = NW_MODEL[live.planner_model || PLANNER_DEFAULT];
  return html`<div class="nw-body">
    ${live.error && html`<${Err} text=${`${live.error} The plan is still here: you can press Start again.`} />`}
    <div class="row" style="gap: 6px 12px; align-items: baseline"><h3>Plan</h3>
      <span class="small soft">${action && action.plan === false ? "the action's own: there's no planner for it" : `by the planner (${plannerName})${live.planner_cost_usd != null ? ` · $${live.planner_cost_usd.toFixed(2)}` : ""}`} · nothing has run yet</span></div>
    ${steps.length ? html`<ol class="stack" style="gap: 8px; padding-left: 22px">${steps.map((s) => html`<li class="stack tight"><span>${s.what}</span>
        ${(s.touches || []).length > 0 && html`<span class="row" style="gap: 6px">${s.touches.map((t) => html`<span class="label mono" style="padding-right: 8px">${t}</span>`)}</span>`}</li>`)}</ol>`
      : html`<p class="small soft">${action && action.plan === false ? "No steps: this action has no planner." : "No steps: the planner gave none."}</p>`}
    <dl class="defs">
      ${recordCovers(live, action && action.object).length > 0 && html`<dt>Covers</dt><dd><span class="row" style="gap: 6px">${recordCovers(live, action && action.object).map((c) => html`<${ItemPill} key=${ref(c)} ...${c} />`)}</span></dd>`}
      ${!live.number && live.repo && html`<dt>Repository</dt><dd class="mono">${live.repo}</dd>`}
      ${live.notes && html`<dt>Your notes</dt><dd>${live.notes}</dd>`}
      ${(spec.pins || []).length > 0 && html`<dt>Pinned</dt><dd>${spec.pins.map((x) => x.label).join(" · ")}</dd>`}
      <dt>Persona</dt><dd>${action ? action.persona_name : spec.persona}</dd>
      <dt>Effort</dt><dd>${spec.effort}</dd>
      <dt>Ends with</dt><dd>${action ? `${action.result_words}. ${action.ceiling}` : ""}</dd></dl>
    ${action && action.models.length > 1 && html`<div class="stack" style="gap: 6px"><span id="lp-model" class="eyebrow">Session model</span>
      <div role="radiogroup" aria-labelledby="lp-model" class="seg" style="align-self: flex-start">${action.models.map((m) => html`<button role="radio" aria-checked=${chosen === m ? "true" : "false"} onClick=${() => setModel(m)}>${NW_MODEL[m] || m}</button>`)}</div>
      <span class="small soft">${chosen !== pick ? `${NW_MODEL[chosen] || chosen}: your choice now.` : yours || !live.planner_pick ? `${NW_MODEL[chosen] || chosen}: from the brief.` : `${NW_MODEL[chosen] || chosen}: the planner's pick.`}</span></div>`}
    ${(spec.docs || []).length > 0 && html`<div class="stack tight"><${Eyebrow}>Docs to read${spec.docs_query ? ` · searched “${spec.docs_query}”` : ""}<//>
      <ul class="stack" style="gap: 4px">${spec.docs.map((d) => html`<li class="passage"><span><b>${d.link}</b><span class="soft" style="font-size: 13px">${d.why}</span></span></li>`)}</ul></div>`}
    <label class="nw-field">Briefing <span class="nw-sub">${action && action.plan === false ? "optional" : "the planner wrote this; edit freely"} · goes into the first prompt</span>
      <textarea class="mono" rows="6" value=${shownBrief} onInput=${(e) => setBrief(e.target.value)} /></label>
    <div class="row"><button class="primary" disabled=${act.busy} onClick=${() => onStart(chosen, shownBrief)}>Start</button>
      <button class="plain" disabled=${act.busy} onClick=${onEdit}>Edit the brief and plan again</button></div>
  </div>`;
}

// The run (005 FR-007): the session in a compact SessionView, its asks inline.
function LaunchRun({ live, asks }) {
  const sessions = useLoad(() => api("shells").catch(() => []), [], 3000);
  const session = live.session ? (sessions.data || []).find((s) => s.name === live.session) : null;
  if (!live.session || !session) return html`<div class="nw-body"><p role="status" class="row" style="font-weight: 600"><${StateIcon} kind="run" />${live.state === "starting" ? "Starting the session…" : "Waiting for the session to show up…"}</p>
    <p class="small soft">This can take a moment while its checkout is made.</p></div>`;
  return html`<div class="nw-body"><${SessionView} key=${session.name} session=${session} mode="compact" asks=${asks} onGone=${sessions.reload} /></div>`;
}

// What this Launch's session handed in, or the pull request it opened (005 R2).
function useLaunchResults(live) {
  const name = live && live.session;
  const named = useLoad(() => (name ? api(`results${params({ session: name })}`).then((r) => r.results) : Promise.resolve([])), [name, live && live.result], 3000);
  return { list: live ? (named.data || []).filter((r) => r.launch === live.id || r.id === live.result) : [], reload: named.reload };
}

function LaunchResult({ live, results, reload, onNote }) {
  const mine = results.list;
  return html`<div class="nw-body">
    ${live.state === "failed" && html`<${Err} text=${live.error || "It stopped."} />`}
    ${live.state === "dismissed" && html`<p class="small soft">Set aside.${(live.drafts || []).some((d) => d.state === "filed") ? "" : " Nothing was filed."}</p>`}
    ${(live.drafts || []).length > 0 && html`<${DraftsResult} item=${live} reload=${reload} onNote=${onNote} />`}
    ${mine.map((r) => html`<${ResultView} key=${r.id} r=${r} reload=${() => { results.reload(); return reload(); }} where="Needs you" />`)}
    ${live.state === "done" && !(live.drafts || []).length && !mine.length && html`<p class="small soft">Loading the result…</p>`}
  </div>`;
}

// One Launch, from brief to result. The record (hubd's, 005 R1) is the stage: the page only holds the brief until Plan.
function LaunchModal({ open, work, asks, reload, onClose, onBehind }) {
  const dialog = useRef();
  const [id, setId] = useState(open.id || null);
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState(null);
  const { list: actions, error: actionsError } = useLaunchActions(work.templates);
  const { data: overview } = useLoad(() => api("overview"), []);
  const act = useAct(reload);
  const [confirm, confirmDialog] = useConfirm();
  useEffect(() => { dialog.current.showModal(); }, []);
  const live = id ? work.items.find((i) => i.id === id) || null : null;
  const action = actions && live ? actions.find((a) => a.id === live.action) : null;
  const stage = !live || live.state === "offered" || editing ? "brief" : live.stage || "brief";
  const stopped = live && (live.state === "failed" ? "stopped" : live.state === "dismissed" ? "set aside" : null);
  const results = useLaunchResults(live);
  // A session that ends in a pull request hands in nothing: its record stays at run, and the result is the PR the hub found.
  const shown = stage === "failed" || stage === "dismissed" || (stage === "run" && results.list.length > 0) ? "result" : stage;
  const running = live && ["planning", "starting", "running", "started"].includes(live.state);
  const close = () => onClose();
  // 005 FR-008: after planning it can go on without you; its asks and its result come to Needs you.
  const background = () => act.run(async () => {
    await post(`new-work/${live.id}/background`, { on: true });
    onBehind({ id: live.id, name: live.session, title: live.title });
  });
  const cancel = () => confirm({ title: live.state === "planning" ? "Stop the planner?" : "Stop the session?", danger: true, label: "Stop",
    text: live.state === "planning" ? "Nothing has run yet. The brief stays in the record, set aside." : `Stops ${live.session || "the session"}. Nothing it hasn't handed in is kept.` },
  () => act.run(() => post(`new-work/${live.id}/cancel`)));
  const setAside = () => act.run(async () => { await post(`new-work/${live.id}/dismiss`); onClose(); });
  const start = (model, brief) => act.run(() => post(`new-work/${live.id}/approve`, { model, brief }));
  const seed = live ? { ...live, from: open.from || live.from, steward: open.steward, repos: live.repos } : open;
  const title = live ? `${live.title}${live.repo ? ` · ${live.number ? recordCovers(live, action && action.object).map(ref).join(", ") : live.repo}` : ""}` : "Launch";
  const by = live ? live.by : open.by;
  return html`${confirmDialog}<dialog ref=${dialog} class="nw" aria-labelledby="ln-h" onClose=${close}>
    <div class="nw-head ${by && by !== "you" ? "agent" : ""}">
      ${by === STEWARD && html`<span class="ask-avatar steward-mark" aria-hidden="true">S</span>`}
      <h2 id="ln-h" style="flex: 1; min-width: 0">${by && by !== "you" ? `${by === STEWARD ? "The Steward" : by} suggests · ` : ""}${title}</h2>
      ${live && live.from && html`<span class="label mono" style="padding-right: 8px">from ${live.from.ref || live.from.view}</span>`}
      <button class="square" aria-label="Close" onClick=${close}>×</button></div>
    <div class="nw-stages"><${LaunchStages} stage=${shown} stopped=${stopped} />
      ${!actions ? html`<div class="nw-body"><${Err} text=${actionsError} />${!actionsError && html`<p class="soft">Loading…</p>`}</div>`
        : shown === "brief" ? html`<${LaunchBrief} key=${`${id}-${editing}`} seed=${seed} actions=${actions} templates=${work.templates} groups=${overview ? overview.groups : []}
            busyId=${live && ["offered", "planned"].includes(live.state) ? live.id : null}
            onCancel=${editing ? () => setEditing(false) : null} onPlanned=${(w) => { setId(w.id); setEditing(false); reload(); }} />`
        : shown === "planning" ? html`<div class="nw-body" role="status"><span class="row" style="font-weight: 600; font-size: 18px"><${StateIcon} kind="run" />The planner is reading</span>
            <span class="mono soft" style="font-size: 12.5px">claude -p · ${NW_MODEL[live.planner_model || PLANNER_DEFAULT]} · read-only hub tools · up to a few minutes</span>
            <p class="small soft">Nothing runs yet. You read the plan before any session starts.</p></div>`
        : shown === "plan" ? html`<${LaunchPlan} key=${live.moved} live=${live} action=${action} act=${act} onEdit=${() => setEditing(true)} onStart=${start} />`
        : shown === "run" ? html`<${LaunchRun} live=${live} asks=${asks} />`
        : html`<${LaunchResult} live=${live} results=${results} reload=${reload} onNote=${setNote} />`}</div>
    <div class="nw-foot">
      <${Err} text=${act.error} />
      <span role="status" class="small" style="flex: 1 1 260px">${note || ""}</span>
      ${live && !editing && ["planning", "plan", "run"].includes(stage) && html`<button class="plain" disabled=${act.busy} onClick=${background}>Send to background</button>`}
      ${running && !editing && html`<button class="plain" disabled=${act.busy} onClick=${cancel}>${live.state === "planning" ? "Stop planner" : "Stop session"}</button>`}
      ${live && ["offered", "planned", "failed"].includes(live.state) && html`<button class="plain" disabled=${act.busy} onClick=${setAside}>${live.state === "offered" ? "Not now" : "Set aside"}</button>`}
      ${live && live.state === "done" && (live.drafts || []).some((d) => d.state === "draft") && html`<button class="plain" disabled=${act.busy} onClick=${setAside}>Set aside</button><${Discard} item=${live} reload=${reload} onDone=${onClose} />`}
      ${live && live.state === "dismissed" && (live.drafts || []).length > 0 && html`<button class="primary" disabled=${act.busy} onClick=${() => act.run(() => post(`new-work/${live.id}/bring_back`))}>Bring back</button>`}
      ${live && live.state === "failed" && !editing && html`<button disabled=${act.busy} onClick=${() => setEditing(true)}>Edit the brief and plan again</button>`}
      <button class="plain" onClick=${close}>${running ? "Close · keeps running" : "Close"}</button></div></dialog>`;
}

// Setting aside keeps drafts to bring back; this is for the ones you never want to see again.
function Discard({ item, reload, onDone }) {
  const [asking, setAsking] = useState(false);
  const act = useAct(reload);
  const waiting = item.drafts.filter((d) => d.state === "draft").length;
  return html`<button class="plain danger" disabled=${act.busy} onClick=${() => setAsking(true)}>Discard…</button><${Err} text=${act.error} />
    ${asking && html`<${Confirm} title=${`Discard ${count(waiting, "draft")}?`} danger label="Discard"
      text="They're deleted and can't be brought back. Issues you've filed stay on GitHub, and drafts you sent to the Steward stay with it."
      onNo=${() => setAsking(false)} onYes=${() => { setAsking(false); act.run(async () => { await post(`new-work/${item.id}/discard`); if (onDone) onDone(); }); }} />`}`;
}

function SetAside({ item, reload }) {
  const act = useAct(reload);
  return html`<div class="ask compact">
    <div class="ask-head"><span class="ask-kind">SET ASIDE</span><span class="small mono soft">${item.repo}</span></div>
    <div class="ask-body"><div class="ask-title">${item.title}</div><p class="small">${count(item.drafts.length, "draft")}.</p><${Err} text=${act.error} />
      <div class="row"><button class="primary" disabled=${act.busy} onClick=${() => act.run(() => post(`new-work/${item.id}/bring_back`))}>Bring back</button>
        <button class="plain" onClick=${() => launch({ id: item.id })}>Open in Launch</button>
        <${Discard} item=${item} reload=${reload} /></div></div></div>`;
}

// A session the Steward (or another session) suggested: yours to read and change in Launch, and nothing runs until you press Start.
function SuggestedSession({ item, compact, reload, where = "Needs you" }) {
  const act = useAct(reload);
  const refs = recordCovers(item).map(ref);
  return html`<article class="ask calm ${item.by === STEWARD ? "steward" : ""} ${compact ? "compact" : ""}">
    <div class="ask-head">${item.by === STEWARD && html`<span class="ask-avatar steward-mark" aria-hidden="true">S</span>`}<span class="small mono">${item.by}</span>${item.by === STEWARD && html`<span class="small">Steward</span>`}<span class="ask-kind">${item.state === "planned" ? (compact ? "SESSION · PLAN READY" : "PLAN READY") : item.state === "failed" ? "STOPPED" : compact ? "SESSION · SUGGESTED" : "SUGGESTED SESSION"}</span></div>
    <div class="ask-body"><h3 class="ask-title">${item.title} ${refs[0]}${refs.length > 1 ? `, also covering ${refs.slice(1).join(", ")}` : ""}</h3>
      <p class="small"><span class="nw-why-word" style="font-size: 17px">why </span>${item.why}</p>
      <p class="small soft">${item.notes ? `Proposed notes: “${item.notes}” ` : ""}${item.state === "planned" ? "The planner wrote a plan. Nothing has run: read it, and start the session if it's right." : "A planner reads this first. Nothing runs until you've read its plan."}</p>
      ${item.error && html`<p class="small" role="alert">${item.error}</p>`}<${Err} text=${act.error} />
      <div class="row"><button class="primary" onClick=${() => launch({ id: item.id, from: { view: where === "SessionView" ? "Needs you" : where } })}>${item.state === "planned" ? "Read the plan" : "Launch…"}</button>
        <button class="plain" disabled=${act.busy} onClick=${() => act.run(() => answerAt(`w:${item.id}`, { verdict: "dismiss" }, where))}>Not now</button></div></div></article>`;
}

function WorkWaiting({ item, compact, reload, where = "Needs you" }) {
  if (item.number) return html`<${SuggestedSession} item=${item} compact=${compact} reload=${reload} where=${where} />`;
  const act = useAct(reload);
  const steward = item.by === STEWARD;
  const undrafted = item.drafts.filter((d) => d.state === "draft").length;
  const line = item.state === "offered" ? item.why
    : item.state === "failed" ? item.error
    : item.state === "planned" && item.error ? item.error
    : item.state === "planned" ? "The planner wrote a plan. Nothing has run: read it, and start the session if it's right."
    : `${count(undrafted, "draft")} waiting for you.`;
  const kind = `${compact ? "NEW WORK · " : ""}${item.state === "offered" ? "SUGGESTED" : item.state === "failed" ? "STOPPED" : item.state === "planned" ? "PLAN READY" : "DRAFTS READY"}`;
  return html`<div class="ask calm ${steward ? "steward" : ""} ${compact ? "compact" : ""}">
    <div class="ask-head"><span class="ask-kind">${kind}</span><span class="small mono">${item.by === "you" ? "you" : item.by}</span><span class="small mono soft">${item.repo}</span></div>
    <div class="ask-body"><div class="ask-title">${item.title}</div><p class="small">${line}</p><${Err} text=${act.error} />
      <div class="row"><button class="primary" onClick=${() => launch({ id: item.id })}>${item.state === "offered" ? "Launch…" : "Open in Launch"}</button>
        <button class="plain" disabled=${act.busy} onClick=${() => act.run(() => answerAt(`w:${item.id}`, { verdict: "dismiss" }, where))}>${item.state === "offered" ? "Not now" : "Set aside"}</button>
        ${item.state === "done" && html`<${Discard} item=${item} reload=${reload} />`}</div></div></div>`;
}

// where: the view the card is in, which hubd records with your answer (003 FR-011). Answers go through interaction.answer.
const answerAt = (id, body, where) => post(`interactions/${encodeURIComponent(id)}/answer`, { ...body, where });

function Ask({ ask, compact, onDone, onShow, where = "SessionView" }) {
  const steward = ask.session === STEWARD;
  const pending = ask.state === "pending";
  const permission = ask.kind === "permission";
  const questions = permission || !ask.input ? [] : ask.input.questions;
  const act = useAct(onDone);
  const [denying, setDenying] = useState(false);
  const [reason, setReason] = useState("");
  const [values, setValues] = useState({});
  const answer = (body) => act.run(() => answerAt(`a:${ask.id}`, body, where));
  const valueOf = (q) => values[q.question] || { picked: [], other: false, text: "" };
  const answerOf = (q) => {
    const v = valueOf(q);
    const typed = v.other && v.text.trim() ? [v.text.trim()] : [];
    return [...v.picked, ...typed];
  };
  const ready = questions.length > 0 && questions.every((q) => answerOf(q).length > 0);
  const send = () => answer({ verdict: "answer", answers: Object.fromEntries(questions.map((q) => [q.question, answerOf(q)])) });
  const a = ask.agent;
  const origin = `${a ? `${a.title} · ${whereFrom(a)}` : "Session"} · ${pending ? `waiting ${waitedWords(ask.waited)}` : "answered"}`;
  const left = ask.left === null ? "until you answer" : clock(ask.left);
  const waitText = ask.terminal
    ? `Also open in the terminal, and whichever answer comes first wins. Hub waits ${ask.left === null ? "until you answer" : `${left} more`}.`
    : permission ? `Waits for you here for ${left} more, then it's refused. Nothing runs until you allow it.`
    : `Waits for you here${ask.left === null ? "" : ` for ${left} more`}. Esc in its terminal cancels the question.`;
  const [resultText, icon, mood] = pending ? [] : askResult(ask);
  const kindWord = permission ? `PERMISSION · ${hubTool(ask.tool).toUpperCase()}` : steward ? "DECISION" : "QUESTION";
  return html`<article class="ask ${pending ? "" : "done"} ${compact ? "compact" : ""} ${steward ? "steward" : ""}" aria-label=${`${permission ? "Permission request" : steward ? "Decision for you" : "Question"} from ${ask.session}, ${pending ? "waiting" : "answered"}`}>
    <div class="ask-head"><span class="ask-avatar" aria-hidden="true">${steward ? "S" : ((a && a.persona) || "?")[0].toUpperCase()}</span>
      <span class="stack" style="gap: 0; flex: 1; min-width: 0; line-height: 1.3">
        <span class="row" style="gap: 2px 8px"><b class="mono" style="font-size: 14px; font-weight: 600; overflow-wrap: anywhere">${ask.session}</b>${a && html`<span style="font-size: 13px">${a.persona[0].toUpperCase()}${a.persona.slice(1)}</span>`}</span>
        <span class="soft" style="font-size: 12.5px; overflow-wrap: anywhere">${origin}</span></span>
      <span class="ask-kind">${kindWord}</span></div>
    <div class="ask-body">
      ${permission && html`<div class="stack" style="gap: 10px"><h3 class="ask-title">${toolTitle(ask.tool)}</h3>
        <${AskContent} ask=${ask} />
        ${ask.input && typeof ask.input.description === "string" && html`<p style="font-size: 14.5px"><span class="ask-why">why</span> ${ask.input.description}</p>`}</div>`}
      ${!permission && !pending && questions.map((q) => html`<div class="stack" style="gap: 4px">${q.header && html`<${Eyebrow} soft>${q.header}<//>`}<h3 class="ask-question">${q.question}</h3></div>`)}
      ${!permission && pending && questions.map((q) => html`<${AskQuestion} key=${q.question} q=${q} steward=${steward} value=${valueOf(q)} onChange=${(v) => setValues({ ...values, [q.question]: v })} />`)}
      ${pending && permission && html`<div class="stack" style="gap: 10px">
        <div class="row" style="gap: 8px">
          <button class="primary" disabled=${act.busy || ask.too_long} onClick=${() => answer({ verdict: "allow" })}>Allow once</button>
          ${ask.always && !ask.too_long && html`<button disabled=${act.busy} onClick=${() => answer({ verdict: "always" })}>Always allow ${ask.always}</button>`}
          <button aria-expanded=${denying ? "true" : "false"} disabled=${act.busy} onClick=${() => setDenying(!denying)}>Deny…</button></div>
        ${denying && html`<div class="ask-deny stack" style="gap: 8px">
          <label class="stack" style="gap: 4px; font-size: 14px; font-weight: 500">Tell Claude why, or what to do instead
            <textarea rows="2" value=${reason} placeholder="e.g. push after the boot test passes" onInput=${(e) => setReason(e.target.value)}></textarea></label>
          <div class="row" style="gap: 8px"><button class="ask-deny-send" disabled=${act.busy} onClick=${() => answer({ verdict: "deny", reason })}>Deny and send</button>
            <button class="plain" onClick=${() => setDenying(false)}>Cancel</button></div></div>`}</div>`}
      ${pending && !permission && html`<div class="row" style="gap: 8px 12px">
        <button class=${ready ? "primary" : ""} disabled=${act.busy || !ready} onClick=${send}>${steward ? "Decide" : "Send answer"}</button>
        <span class="small soft">${ready ? (steward ? "The Steward gets your choice as its answer and continues." : "Claude gets this as the answer to its question.") : ask.terminal ? "Pick one, or answer in the terminal." : "Pick one."}</span></div>`}
      <${Err} text=${act.error} />
      ${pending && html`<div class="ask-foot">
        <span role="img" aria-label=${`Hub waits ${left} more`} class="ask-meter"><span style=${`width: ${ask.left === null ? 100 : Math.round((100 * ask.left) / ask.wait)}%`}></span></span>
        <span class="small soft" style="flex: 1 1 200px">${waitText}</span>
        ${onShow && html`<button class="plain" onClick=${() => onShow(ask.session)}>Show in terminal</button>`}</div>`}
      ${!pending && html`<div role="status" class="ask-result ${mood}"><${StateIcon} kind=${icon === "check" ? "pass" : icon === "cross" ? "fail" : "open"} label="" /><span style="flex: 1 1 200px; font-size: 14.5px">${resultText}</span></div>`}
    </div></article>`;
}

// --- Needs you: one Feed of interactions, in a modal over any view (003 FR-001–003 FR-017, 003 FR-018–003 FR-022) ------------
// The list is hubd's interaction.list: asks, decisions and new work in one shape. An answer goes to
// interaction.answer, which sends it on to the source's own op; nothing here decides what an answer may do.
const BLOCKING = (r) => r.blocking;
const KIND_LABEL = { permission: "Permission", question: "Question", decision: "Decision", suggestion: "Suggestion", result: "Result" };
const STATUS_WORD = { pending: "waiting for you", allowed: "allowed", always: "always allowed", denied: "denied", answered: "answered", started: "started",
  dismissed: "dismissed", terminal: "answered in the terminal", timeout: "timed out", ended: "ended" };
const needsYou = (detail = {}) => window.dispatchEvent(new CustomEvent("hub-needs-you", { detail }));
// Only a session hubd still knows gets a chip with a state; a name it doesn't know is just the name, never "running".
const sessionOfRow = (r) => (r.session && r.persona ? { name: r.session, attached: 0, agent: { persona: r.persona.id, persona_name: r.persona.name, initials: r.persona.initials,
  family: r.persona.family, ended: r.persona.ended, waiting: r.blocking } } : null);
const handledWords = (r) => {
  const h = r.handled;
  const who = !h ? "" : h.by === "terminal" ? " in the terminal" : ` by ${h.by}${h.where ? `, in ${h.where}` : ""}`;
  return `${STATUS_WORD[r.status] || r.status}${who}${r.settled ? `, ${ago(r.settled * 1000)}` : ""}`;
};
const leftWords = (left) => [left.runs !== undefined && count(left.runs, "run"), left.hours !== undefined && `${left.hours} h`].filter(Boolean).join(" and ") || "until you end it";
// A Go's or merge's card. Approving through the login is your word (003 FR-005); a session's own words are marked as theirs.
const DECISION_STATE = { requested: "Waiting for you", current: "Allowed", using: "Merging now", ended: "Ended" };

function DecisionRow({ d, onChanged, where = "Needs you" }) {
  const act = useAct(onChanged);
  const [words, setWords] = useState("");
  const [narrow, setNarrow] = useState(null);
  const [reason, setReason] = useState("");
  const [unit, setUnit] = useState(d.for_hours ? "hours" : "runs");
  const [amount, setAmount] = useState(d.for_hours || (d.ends && d.ends.runs) || 1);
  const go = d.kind === "go";
  const asked = d.state === "requested";
  const eye = go && d.scope.actions.includes("eye-test");
  const actions = narrow || (go ? d.scope.actions : []);
  const toggle = (a) => setNarrow(actions.includes(a) ? actions.filter((x) => x !== a) : [...actions, a]);
  const asWas = unit === (d.for_hours ? "hours" : "runs") && Number(amount) === Number(d.for_hours || (d.ends && d.ends.runs) || 1);
  const send = (verdict, body = {}) => act.run(() => answerAt(d.id, { verdict, ...body }, where));
  const approve = () => send("approve", { words: words || null, scope: narrow ? { actions: narrow } : null, ends: go && !asWas ? { [unit]: Number(amount) } : null });
  const left = d.left || {};
  return html`<article class="stack" style="gap: 6px" aria-label=${`${DECISION_STATE[d.state]}: ${d.says}`}>
    <div class="row" style="gap: 8px"><span class="badge ${asked ? "" : d.state === "ended" ? "dim" : ""}">${DECISION_STATE[d.state]}</span><span class="mono small">${d.id}</span>
      <span class="small soft">made ${ago(d.made * 1000)}${d.ended ? `, ended ${ago(d.ended * 1000)}` : ""}</span></div>
    <p style="overflow-wrap: anywhere">${d.says}.</p>
    ${d.kind === "merge" && html`<p class="small">Applies to head <span class="mono">${d.scope.head.slice(0, 12)}</span> only. If the pull request's head moves, it ends (003 FR-008).</p>`}
    ${eye && html`<p class="small"><b>Eye test:</b> you look at the device yourself. It ends with its runs or hours, and is never granted for good.</p>`}
    ${d.words && html`<p class="small" style="overflow-wrap: anywhere"><span class="soft">Your words: </span>${d.words}</p>`}
    ${d.asked_by && html`<p class="small soft">Asked for by ${d.asked_by}, in its own words, which aren't yours: <span style="overflow-wrap: anywhere">${d.why}</span></p>`}
    ${!d.asked_by && d.why && html`<p class="small soft" style="overflow-wrap: anywhere">Asked for by a hub shell, in its own words: ${d.why}</p>`}
    ${d.why_ended && html`<p class="small">Ended: ${d.why_ended}</p>`}
    ${(d.state === "current" || d.state === "using") && html`<p class="small">Left: ${leftWords(left)}.</p>`}
    ${asked && html`<div class="stack" style="gap: 8px">
      ${go && html`<fieldset class="row" style="gap: 6px 14px; border: 0; padding: 0"><legend class="small soft">Untick what you don't want to allow</legend>
        ${d.scope.actions.map((a) => html`<label class="row small" style="gap: 6px"><input type="checkbox" checked=${actions.includes(a)} onChange=${() => toggle(a)} /> ${a}</label>`)}</fieldset>`}
      ${go && html`<div class="row" style="gap: 8px 14px"><span class="small">Device: <span class="mono">${d.scope.device}</span>, session: <span class="mono">${d.scope.session}</span></span>
        <label class="row small" style="gap: 6px">Ends after <input type="number" min="1" style="width: 5em" value=${amount} onInput=${(e) => setAmount(e.target.value)} />
          <select aria-label="Runs or hours" value=${unit} onChange=${(e) => setUnit(e.target.value)}><option value="runs">runs</option><option value="hours">hours</option></select></label></div>`}
      <label class="stack small" style="gap: 4px">Your words, if you want them on the record<input value=${words} onInput=${(e) => setWords(e.target.value)} /></label>
      <div class="row" style="gap: 8px"><button class="primary" disabled=${act.busy || (go && !actions.length) || Number(amount) <= 0} onClick=${approve}>Approve</button>
        <input aria-label="Why not" value=${reason} placeholder="Why not, if you like" onInput=${(e) => setReason(e.target.value)} />
        <button disabled=${act.busy} onClick=${() => send("deny", { why: reason || null })}>Say no</button></div></div>`}
    ${d.state === "current" && html`<div class="row"><button disabled=${act.busy} onClick=${() => send("end")}>End now</button></div>`}
    <${Err} text=${act.error} /></article>`;
}

// One card per kind (003 FR-003–003 FR-009). The links say whose it is and what it's about (003 FR-017).
function InteractionCard({ item, dense, where, reload }) {
  const [open, setOpen] = useState(false);
  const chip = sessionOfRow(item);
  const links = html`<div class="icard-links row" style="gap: 6px">
    ${chip ? html`<${SessionChip} session=${chip} pending=${item.blocking ? 1 : 0} />` : item.session ? html`<span class="small soft">Session <span class="mono">${item.session}</span>, no longer listed</span>`
      : html`<span class="small soft">${item.kind === "decision" ? "Recorded by you" : "From you"}</span>`}
    ${item.items.map((i) => html`<${ItemPill} key=${ref(i)} kind=${i.kind} repo=${i.repo} number=${i.number} />`)}</div>`;
  const d = item.detail;
  const settled = item.status !== "pending" && !(item.kind === "decision" && item.status === "allowed");
  const body = () => {
    if (item.kind === "permission" || item.kind === "question") return html`<${Ask} ask=${d} compact=${settled} onDone=${reload} where=${where} />`;
    if (item.kind === "result" && d.type) return html`<${ResultView} r=${d} reload=${reload} where=${where} />`;
    if (item.kind === "decision") return html`<div class="ask calm ${settled ? "done" : ""}"><div class="ask-head"><span class="ask-kind">${d.kind === "go" ? (d.scope.actions.includes("eye-test") ? "GO · EYE TEST" : "GO") : "MERGE"}</span>
      <span class="small mono">${d.asked_by || "you"}</span></div><div class="ask-body"><${DecisionRow} key=${`${d.id}-${d.state}`} d=${d} onChanged=${reload} where=${where} /></div></div>`;
    if (settled && d.state === "dismissed" && (d.drafts || []).length) return html`<${SetAside} item=${d} reload=${reload} />`;
    if (settled) return html`<div class="ask calm done"><div class="ask-head"><span class="ask-kind">${KIND_LABEL[item.kind].toUpperCase()}</span><span class="small mono">${d.by}</span></div>
      <div class="ask-body"><p class="ask-title">${d.title}</p></div></div>`;
    return html`<${WorkWaiting} item=${d} reload=${reload} where=${where} />`;
  };
  const summary = item.kind === "permission" ? toolTitle(d.tool) : item.kind === "question" ? ((d.input && d.input.questions) || [{}])[0].question || "Question"
    : item.kind === "decision" ? d.says : item.kind === "result" && d.type ? resultTitle(d) : d.title;
  if (dense && !open) {
    return html`<div class="icard dense ${item.blocking ? "waits" : ""}" data-waits=${item.blocking ? "" : undefined}>
      <button class="icard-line" aria-expanded="false" onClick=${() => setOpen(true)}>
        <span class="ask-kind">${KIND_LABEL[item.kind].toUpperCase()}</span><span class="t">${summary}</span>
        <span class="small soft">${item.session || "you"} · ${item.status === "pending" ? `waiting ${waitedWords(item.waited)}` : handledWords(item)}</span></button></div>`;
  }
  return html`<div class="icard stack" style="gap: 8px">
    ${dense && html`<button class="plain small" style="align-self: flex-start" aria-expanded="true" onClick=${() => setOpen(false)}>Fold to one line</button>`}
    ${links}${body()}
    ${settled && html`<p class="small soft" role="status">${KIND_LABEL[item.kind]}: ${handledWords(item)}.</p>`}</div>`;
}

// 003 FR-014–003 FR-016: Blocking (oldest first), Suggested (decisions asked for first), Results ready.
const FEED_FILTERS = [["all", "All"], ["steward", "The Steward"], ["others", "Other sessions"]];
const feedFilter = (filter) => (filter === "steward" ? (r) => r.session === STEWARD : filter === "others" ? (r) => r.session && r.session !== STEWARD : () => true);

function Feed({ items, filter = "all", dense, session, where = "Needs you", reload }) {
  const shown = items.filter((r) => r.status === "pending").filter(feedFilter(filter)).filter((r) => !session || r.session === session);
  const blocking = shown.filter(BLOCKING).sort((a, b) => a.made - b.made);
  const asked = shown.filter((r) => r.kind === "decision");
  const suggested = shown.filter((r) => r.kind === "suggestion");
  const results = shown.filter((r) => r.kind === "result");
  const cards = (rows) => rows.map((r) => html`<${InteractionCard} key=${r.id} item=${r} dense=${dense} where=${where} reload=${reload} />`);
  if (!shown.length) return html`<div role="status" class="ask-clear"><span class="ask-clear-word">all clear</span><span>Nothing ${filter === "all" && !session ? "" : "of this kind "}is waiting on you. Sessions keep working, and anything new shows up here.</span></div>`;
  return html`<div class="stack feed ${dense ? "dense" : ""}" style="gap: 22px">
    ${blocking.length > 0 && html`<section class="stack" style="gap: 10px" aria-label=${`Blocking, ${blocking.length}`}><h3 class="eyebrow">Blocking · ${blocking.length} · oldest first</h3>
      <p class="small soft">A session's turn waits on each of these.</p>${cards(blocking)}</section>`}
    ${(asked.length > 0 || suggested.length > 0) && html`<section class="stack" style="gap: 10px" aria-label=${`Suggested, ${asked.length + suggested.length}`}><h3 class="eyebrow">Suggested · ${asked.length + suggested.length}</h3>
      ${asked.length > 0 && html`<h4 class="small" style="font-weight: 600">Decisions asked for</h4><p class="small soft">Nothing happens until you approve. Only a login records one, and what a session says in its own words isn't yours.</p>${cards(asked)}`}
      ${cards(suggested)}</section>`}
    ${results.length > 0 && html`<section class="stack" style="gap: 10px" aria-label=${`Results ready, ${results.length}`}><h3 class="eyebrow">Results ready · ${results.length}</h3>${cards(results)}</section>`}
  </div>`;
}

// The modal's own filters beside the Feed's: what you've allowed that stands (003 FR-020), every decision, and what's settled.
const NEEDS_VIEWS = [...FEED_FILTERS, ["grants", "Active grants"], ["decisions", "Decisions"], ["settled", "Settled"]];

function NeedsYouModal({ initial, data, asks, onClose }) {
  const ref = useRef();
  const [filter, setFilter] = useState(NEEDS_VIEWS.some(([id]) => id === initial.filter) ? initial.filter : "all");
  const [session, setSession] = useState(initial.session || "");
  const [dense, setDense] = useState(false);
  const seen = useRef(new Map()); // id → how it was when this view first showed it
  useEffect(() => { ref.current.showModal(); }, []);
  const rows = [...data.items, ...data.grants];
  for (const r of rows) if (!seen.current.has(r.id)) seen.current.set(r.id, r.status);
  // 003 FR-011: what was waiting or standing when you looked, and has settled since; until you close this.
  const handled = rows.filter((r) => ["pending", "allowed"].includes(seen.current.get(r.id)) && r.status !== seen.current.get(r.id));
  const names = [...new Set(rows.map((r) => r.session).filter(Boolean))].sort();
  const bySession = (r) => !session || r.session === session;
  const grants = data.grants.filter(bySession);
  const cards = (list) => list.map((r) => html`<${InteractionCard} key=${r.id} item=${r} dense=${dense} where="Needs you" reload=${asks.reload} />`);
  const settledRows = data.items.filter((r) => r.status !== "pending").filter(bySession);
  const pending = data.counts.pending;
  return html`<dialog ref=${ref} class="needs sheet" aria-labelledby="needs-h" onClose=${onClose}>
    <div class="needs-head"><h2 id="needs-h">Needs you</h2>
      <span class="small" role="status">${pending ? `${count(pending, "thing")} waiting${data.counts.blocking ? `, ${data.counts.blocking} blocking` : ""}` : "Nothing waiting"}${asks.stale ? " · hubd can't be reached: showing what was last read" : ""}</span>
      <button class="square" aria-label="Close Needs you" onClick=${() => ref.current.close()}>×</button></div>
    <div class="needs-body stack" style="gap: 18px">
      <div class="row" style="gap: 6px 12px">
        <div role="group" aria-label="Show" class="row" style="gap: 6px">${NEEDS_VIEWS.map(([id, label]) => html`<button class="ask-filter" aria-pressed=${filter === id ? "true" : "false"} onClick=${() => setFilter(id)}>${label}${id === "grants" && data.grants.length ? ` (${data.grants.length})` : ""}</button>`)}</div>
        <label class="row small" style="gap: 6px">Session <select value=${session} onChange=${(e) => setSession(e.target.value)}><option value="">every session</option>${names.map((n) => html`<option value=${n}>${n}</option>`)}</select></label>
        <label class="row small" style="gap: 6px"><input type="checkbox" checked=${dense} onChange=${(e) => setDense(e.target.checked)} /> One line each</label></div>
      ${handled.length > 0 && html`<details class="ask-answered"><summary class="small">${count(handled.length, "thing")} handled in this view</summary>
        <ul class="stack" style="gap: 4px; margin-top: 8px">${handled.map((r) => html`<li class="small" key=${r.id}>${KIND_LABEL[r.kind]}${r.session ? ` from ${r.session}` : ""}: ${handledWords(r)}</li>`)}</ul></details>`}
      ${["all", "steward", "others"].includes(filter) && html`<${Feed} items=${data.items} filter=${filter} dense=${dense} session=${session} reload=${asks.reload} />`}
      ${filter === "grants" && html`<section class="stack" style="gap: 10px" aria-label="Active grants">
        <p class="small soft">Goes and merge decisions you've approved that still stand, with what's left. A go ends when its runs or hours are used up; End now stops it sooner. A session can end a go too, and nothing it says makes one current.</p>
        ${cards(grants)}${!grants.length && html`<p class="small soft">Nothing you've allowed is standing.</p>`}</section>`}
      ${filter === "decisions" && html`<section class="stack" style="gap: 10px" aria-label="Decisions">
        <p class="small soft">Your word, kept: waiting, standing and ended. Approved here means your decision, never a GitHub review.</p>
        ${cards(rows.filter((r) => r.kind === "decision").filter(bySession))}</section>`}
      ${filter === "settled" && html`<section class="stack" style="gap: 10px" aria-label="Settled">
        <p class="small soft">Answered, ended or set aside. Asks are kept until hubd restarts, new work for a day, decisions as long as hubd keeps them.</p>
        ${cards(settledRows)}${!settledRows.length && html`<p class="small soft">Nothing settled yet.</p>`}</section>`}
      <${GoPanel} asks=${asks} />
    </div></dialog>`;
}

// --- what's left after a session -----------------------------------------------------------------
const PAST_FILTERS = [["all", "All"], ["interrupted", "Interrupted"], ["ended", "Ended by you"], ["finished", "Finished"]];
const PAST_ENDED = { interrupted: "Interrupted", ended: "Ended by you", finished: "Finished" };
const PAST_TAG = { kept: "WORKTREE KEPT", removed: "WORKTREE REMOVED", none: "NO CHECKOUT" };
const CLEAN_TAG = { safe: "SAFE TO REMOVE", review: "REVIEW FIRST", keep: "KEEP · OPEN PR", inuse: "IN USE", other: "KEEP · NOT THE HUB'S" };
const bytes = (n) => (n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : n >= 1e6 ? `${Math.round(n / 1e6)} MB` : `${Math.round(n / 1e3)} KB`);
const whenAgo = (seconds) => ago(new Date(seconds * 1000).toISOString());

function Transcript({ id, name, onClose }) {
  const ref = useRef();
  const { data, error } = useLoad(() => post("agents/past_transcript", { id }), [id]);
  useEffect(() => { ref.current.showModal(); }, []);
  return html`<dialog ref=${ref} class="transcript" aria-labelledby="tr-h" onClose=${onClose}>
    <div class="row" style="justify-content: space-between; margin: 0"><h2 id="tr-h" class="mono">${name}</h2><button class="square" aria-label="Close" onClick=${onClose}>×</button></div>
    <${Err} text=${error} />
    ${!data && !error && html`<p role="status" class="small soft">Reading the transcript…</p>`}
    ${data && html`<p class="small soft">${data.note}${data.cut ? ` The first ${count(data.cut, "message")} are left out.` : ""}</p>
      <div class="stack" style="gap: 10px">${data.messages.map((m) => html`<div class="tr-msg ${m.role}"><span class="eyebrow soft">${m.role === "user" ? "Prompt" : "Claude"}</span><div class="tr-text">${m.text}</div></div>`)}</div>`}
  </dialog>`;
}

function PastSessions() {
  const [filter, setFilter] = useState("all");
  const [persona, setPersona] = useState("");
  const [repo, setRepo] = useState("");
  // 004 FR-016: hubd narrows by persona, repository and outcome.
  const { data, error, reload } = useLoad(() => post("agents/past", { persona: persona || undefined, repo: repo || undefined, outcome: filter === "all" ? undefined : filter }), [persona, repo, filter]);
  const everything = useLoad(() => post("agents/past"), []);
  const live = useSessions();
  const [resuming, setResuming] = useState(null);
  const [words, setWords] = useState("");
  const [found, setFound] = useState(null);
  const [reading, setReading] = useState(null);
  const [back, setBack] = useState(null);
  const act = useAct(reload);
  useEffect(() => {
    const typed = words.trim();
    if (typed.length < 2) { setFound(null); return undefined; }
    const timer = setTimeout(() => { post("agents/past_search", { words: typed }).then(setFound).catch((e) => setFound({ matches: {}, error: e.message })); }, 400);
    return () => clearTimeout(timer);
  }, [words]);
  const rows = (data ? data.sessions : []).filter((r) => !found || found.matches[r.id]);
  const all = everything.data ? everything.data.sessions : [];
  const personas = [...new Set(all.map((r) => r.persona).filter(Boolean))].sort();
  const repos = [...new Set(all.map((r) => r.repo).filter(Boolean))].sort();
  // 004 FR-018: one already running again says so, instead of offering to resume it twice.
  const runningAgain = (r) => (live.data || []).some((s) => s.name === r.name && s.agent && !s.agent.ended);
  const resume = (r) => { setResuming(r.id); act.run(async () => { try { await post("agents/resume_past", { id: r.id }); setBack(r.name); live.reload(); } finally { setResuming(null); } }); };
  return html`<section class="stack" style="gap: 14px" aria-labelledby="h-hist">
    ${reading && html`<${Transcript} id=${reading.id} name=${reading.name} onClose=${() => setReading(null)} />`}
    <div class="row" style="justify-content: space-between; align-items: flex-end; gap: 12px 20px">
      <div class="stack tight" style="flex: 1 1 380px"><h1 id="h-hist">Resume a past session</h1>
        <span class="small soft">Every session that has ended, with its transcript. Resuming reopens it in tmux with <span class="mono">claude --resume</span>, right where it stopped.</span></div>
      <input type="search" aria-label="Search transcripts" placeholder="Search transcripts" style="flex: 0 1 320px" value=${words} onInput=${(e) => setWords(e.target.value)} /></div>
    <div role="group" aria-label="Filter" class="row" style="gap: 6px">${PAST_FILTERS.map(([id, label]) => html`<button class="ask-filter" aria-pressed=${filter === id ? "true" : "false"} onClick=${() => setFilter(id)}>${label}</button>`)}
      <label class="field"><span>Persona</span><select value=${persona} onChange=${(e) => setPersona(e.target.value)}><option value="">Any</option>${personas.map((p) => html`<option value=${p}>${p}</option>`)}</select></label>
      <label class="field"><span>Repository</span><select value=${repo} onChange=${(e) => setRepo(e.target.value)}><option value="">Any</option>${repos.map((p) => html`<option value=${p}>${p}</option>`)}</select></label>
      ${found && html`<span role="status" class="small soft">${found.error || `${count(rows.length, "transcript")} with these words${found.cut ? ", from the newest only" : ""}`}</span>`}</div>
    <${Err} text=${error || act.error} />
    ${back && html`<p role="status"><span class="mono">${back}</span> is running again. <a href=${hash("shells", { tab: "all", name: back })}>Open it →</a></p>`}
    ${!data && !error && html`<p role="status" class="small soft">Reading transcripts…</p>`}
    ${data && rows.length === 0 && html`<p class="small soft">No sessions here.</p>`}
    <div class="stack" style="gap: 8px">${rows.map((r) => html`<div class="past ${r.kind}" key=${r.id}>
      <div class="stack" style="gap: 3px; flex: 999 1 340px; min-width: 0">
        <div class="row" style="gap: 4px 10px"><strong class="mono">${r.name}</strong><span class="small soft">${r.persona} · ${r.model}</span><span class="small soft">from ${r.number ? `${r.repo}#${r.number}` : r.repo || "the whole project"}</span></div>
        ${r.last && html`<span class="small">“${r.last}”</span>`}
        ${found && found.matches[r.id] && html`<span class="small soft mono">… ${found.matches[r.id]}</span>`}
        <span class="small soft">${PAST_ENDED[r.kind]} ${whenAgo(r.ended)} · ${count(r.turns, "turn")} · transcript <span class="mono">${r.id.slice(0, 8)}</span></span></div>
      <span class="past-tag">${PAST_TAG[r.worktree]}</span>
      <div class="row" style="gap: 6px; flex: none">
        ${runningAgain(r) ? html`<span class="small">Running again · <a href=${hash("shells", { tab: "all", name: r.name })}>Open it</a></span>`
          : r.transcript ? html`<button class="primary" disabled=${act.busy} onClick=${() => resume(r)}>${resuming === r.id ? (r.worktree === "removed" ? "Restoring…" : "Resuming…") : r.worktree === "removed" ? "Restore & resume" : "Resume"}</button>
            <button disabled=${act.busy} onClick=${() => setReading(r)}>Transcript</button>`
          : html`<span class="small soft">Its transcript is gone.</span>`}</div></div>`)}</div>
    <p class="small soft">Claude Code keys transcripts by folder, and a session runs from the same folder when it comes back. When a worktree was removed, the hub recreates it at the same path first: from its branch, or from the pull request. Uncommitted files in a removed worktree don't come back, which is why the hub won't remove one that has them. The Steward isn't listed: it has its own place in the sidebar.</p>
  </section>`;
}

function Cleanup() {
  const { data, error, reload } = useLoad(() => post("agents/cleanup"), []);
  const [picked, setPicked] = useState({});
  const [asking, setAsking] = useState(false);
  const [note, setNote] = useState(null);
  const act = useAct(reload);
  const rows = data ? data.rows : [];
  const safe = rows.filter((r) => r.state === "safe");
  // 004 FR-022: no uncommitted changes, no running session and a merged or closed pull request.
  const settled = safe.filter((r) => r.pr_settled);
  const chosen = safe.filter((r) => picked[r.id]);
  const total = rows.reduce((a, r) => a + r.size, 0);
  const safeSize = safe.reduce((a, r) => a + r.size, 0);
  const size = chosen.reduce((a, r) => a + r.size, 0);
  const remove = () => act.run(async () => {
    setAsking(false);
    const r = await post("agents/cleanup_remove", { ids: chosen.map((x) => x.id) });
    setPicked({});
    setNote(`${r.removed.length} removed.${r.failed.length ? ` Left in place: ${r.failed.map((f) => `${f.id} (${f.error})`).join("; ")}` : ""}`);
  });
  const setAfterMerge = (on) => act.run(() => post("agents/cleanup", { after_merge: on }));
  const percent = total ? Math.round((safeSize / total) * 100) : 0;
  return html`<section class="stack" style="gap: 14px" aria-labelledby="h-clean">
    <div class="row" style="justify-content: space-between; align-items: flex-end; gap: 12px 20px">
      <div class="stack tight" style="flex: 1 1 380px"><h2 id="h-clean" style="font-size: 20px">Worktrees</h2>
        <span class="small soft">Session worktrees in the workspace and read-only checkouts in the hub's state. Transcripts are kept, so removing a worktree never stops a session from being resumed.</span></div>
      ${data && html`<div class="stack" style="gap: 4px; flex: 0 1 320px"><div class="row small" style="justify-content: space-between"><span>${bytes(total)} used</span><span>${bytes(safeSize)} safe to remove</span></div>
        <div class="clean-bar" role="img" aria-label=${`${bytes(total)} used, ${bytes(safeSize)} safe to remove`}><span style=${`width: ${percent}%`}></span></div></div>`}</div>
    <div class="row" style="gap: 8px">
      <button disabled=${!settled.length} title="Rows whose pull request is merged or closed, with nothing uncommitted and no session running" onClick=${() => setPicked(Object.fromEntries(settled.map((r) => [r.id, true])))}>Select safe</button>
      <button class="primary" disabled=${!chosen.length || act.busy} onClick=${() => setAsking(true)}>${chosen.length ? `Remove ${chosen.length} · ${bytes(size)}` : "Remove"}</button>
      <span role="status" class="small" style="flex: 1 1 200px">${note}</span></div>
    ${asking && html`<div role="alertdialog" aria-labelledby="h-conf" class="clean-confirm"><h3 id="h-conf">hubd will run exactly this</h3>
      <pre class="mono small">${chosen.flatMap((r) => r.commands).join("\n")}</pre>
      <span class="small"><span class="mono">worktree remove</span> refuses a dirty tree and <span class="mono">branch -d</span> an unmerged branch. hubd checks each row again first, and leaves it in place if anything has changed. A branch git won't call merged stays, and so do transcripts.</span>
      <div class="row"><button class="primary" onClick=${remove}>Remove ${chosen.length} · ${bytes(size)}</button><button onClick=${() => setAsking(false)}>Cancel</button></div></div>`}
    <${Err} text=${error || act.error} />
    ${!data && !error && html`<p role="status" class="small soft">Checking each worktree and its pull request…</p>`}
    ${data && rows.length === 0 && html`<p class="small soft">No worktrees.</p>`}
    <div class="stack" style="gap: 6px">${rows.map((r) => html`<div class="clean-row" key=${r.id}>
      <input type="checkbox" aria-label=${`Select ${r.id}`} disabled=${r.state !== "safe"} checked=${!!picked[r.id] && r.state === "safe"} onChange=${() => setPicked({ ...picked, [r.id]: !picked[r.id] })} />
      <div class="stack" style="gap: 2px; flex: 999 1 280px; min-width: 0"><span class="mono small clean-path">${r.path}</span><span class="small soft">${r.what}</span>
        ${r.commands.length > 0 && html`<pre class="mono small clean-cmd" aria-label="What removing it runs">${r.commands.join("\n")}</pre>`}</div>
      <span class="past-tag ${r.state}">${CLEAN_TAG[r.state]}</span><span class="mono small" style="flex: none; min-width: 64px; text-align: right">${bytes(r.size)}</span></div>`)}</div>
    ${data && html`<div class="stack" style="gap: 6px; padding-top: 12px; border-top: 1px dotted var(--ink)"><span class="eyebrow">Clean up by itself</span>
      <label class="row small" style="gap: 8px"><input type="checkbox" role="switch" checked=${data.settings.after_merge} disabled=${act.busy} onChange=${(e) => setAfterMerge(e.target.checked)} /> Remove automatically ${data.settings.days} days after the PR merges</label>
      <span class="small soft">Only rows that are safe to remove. Anything with uncommitted files, unpushed commits or a running session is never removed by itself, and neither is anything the hub didn't start. Transcripts are never deleted.</span></div>`}
  </section>`;
}

const needsLabel = (asks) => {
  const c = asks.interactions.counts;
  return `Needs you: ${c.pending ? `${count(c.pending, "thing")} waiting${c.blocking ? `, ${c.blocking} blocking a session` : ""}` : "nothing waiting"}. Open`;
};

// 001 FR-002, 001 FR-003: yellow only when a session's turn waits on you, outlined while anything waits, plain at none.
function NeedsButton({ asks }) {
  const c = asks.interactions.counts;
  const state = c.blocking > 0 ? "blocking" : c.pending > 0 ? "pending" : "none";
  return html`<button class="needs-open ${state === "none" ? "plain" : ""}" data-state=${state} data-waits=${state === "blocking" ? "" : undefined}
    aria-label=${needsLabel(asks)} onClick=${() => needsYou()}>Needs you <span class="ask-tally">${c.pending}</span></button>`;
}

function SessionHistory({ asks }) {
  return html`<main class="page wide"><${SessionTabs} tab="history" asks=${asks} /><div class="stack" style="gap: 32px"><${PastSessions} /><${Cleanup} /></div></main>`;
}

// Until the header has its Needs you button (PR 5), it opens from here too. tab=needs and tab=active open it (Hub).
function SessionTabs({ tab }) {
  return html`<div role="tablist" aria-label="Sessions" class="tabs" style="margin-bottom: 18px">
    <a role="tab" aria-selected=${tab === "all" ? "true" : "false"} href=${hash("shells", { tab: "all" })}>All sessions</a>
    <a role="tab" aria-selected=${tab === "history" ? "true" : "false"} href=${hash("shells", { tab: "history" })}>History & cleanup</a></div>`;
}

function Sessions({ query, asks }) {
  const tab = query.tab || "all";
  if (tab === "history") return html`<${SessionHistory} asks=${asks} />`;
  return html`<${Shells} query=${query} asks=${asks} />`;
}

// 004 FR-012: Running, in four groups by where a session is drawn and whether Claude still runs in it.
const RUN_GROUPS = [["embedded", "Embedded in a view"], ["background", "In the background"], ["finished", "Finished, tmux still open"], ["plain", "Plain shells"]];
const runGroup = (s) => (!s.agent ? "plain" : s.agent.ended ? "finished" : s.agent.view && s.agent.view.mode === "embedded" ? "embedded" : "background");
const readBadgesOnly = () => { try { return localStorage.getItem("sessions-badges") === "1"; } catch { return false; } };

function Shells({ query, asks }) {
  const [kept, setKept] = useState(null);
  // Every 3 s, as the other lists that change under you (003 SC-002): a session started elsewhere shows without a reload.
  const { data, error, reload } = useLoad(() => api("shells"), [], 3000);
  const stopped = useLoad(() => api("agents/stopped").catch(() => []), [], 15000);
  const overview = useLoad(() => api("overview"), []);
  const reloadAll = () => Promise.all([reload(), stopped.reload()]);
  const [discarding, setDiscarding] = useState(null);
  const [ignoring, setIgnoring] = useState(null);
  const [open, setOpen] = useState(query.name || null);
  const [creating, setCreating] = useState(query.new === "1");
  const [badgesOnly, setBadgesOnlyState] = useState(readBadgesOnly);
  const setBadgesOnly = (on) => { setBadgesOnlyState(on); try { localStorage.setItem("sessions-badges", on ? "1" : "0"); } catch { /* it only helps */ } };
  const [confirm, dialog] = useConfirm();
  const act = useAct(reloadAll);
  const list = data || [];
  const current = list.find((s) => s.name === open) || null;
  // Closed first: the old terminal goes away with the old session, and would close the new one's view.
  const resume = (name) => act.run(async () => {
    setOpen(null);
    await post("agents/resume", { name });
    await reloadAll();
    setOpen(name);
  });
  const waitingOn = (name) => asks.open.filter((x) => x.session === name).length;
  // 004 FR-013: badge, state, what waits, where it came from, model and age, and the items it covers.
  const item = (s) => {
    const a = s.agent;
    const words = sessionWords(s);
    const waiting = waitingOn(s.name);
    const covers = coversOf(a);
    const label = `${s.name}: ${a ? `${a.persona_name || a.persona}, ` : ""}${words}${waiting ? `, ${waiting} waiting` : ""}`;
    if (badgesOnly) {
      return html`<button class="sess-badge" aria-pressed=${open === s.name ? "true" : "false"} aria-label=${label} title=${label} onClick=${() => setOpen(s.name)}>
        <${PersonaBadge} persona=${personaOf(a)} hidden />${waiting > 0 && html`<span class="dock-count">${waiting}</span>`}</button>`;
    }
    return html`<button class="sess-item" aria-pressed=${open === s.name ? "true" : "false"} onClick=${() => setOpen(s.name)}>
      <span class="h"><span class="row" style="gap: 8px; flex-wrap: nowrap; min-width: 0"><${PersonaBadge} persona=${personaOf(a)} /><b>${s.name}</b></span>
        <span class="badge ${words === "Waiting for you" ? "mark" : a && a.ended ? "dim" : ""}">${words}</span></span>
      ${waiting > 0 && html`<span class="small" style="font-weight: 600">${waiting} waiting</span>`}
      ${a ? html`<span class="soft" style="font-size: 13px; line-height: 1.4">${originWords(a)} · ${shortModel(a.model)}${a.created ? ` · ${whenAgo(a.created)}` : ""}</span>`
        : html`<span class="soft mono" style="font-size: 12.5px; overflow-wrap: anywhere">${s.cwd}</span>`}
      ${covers.length > 0 && html`<span class="row" style="gap: 6px"><${ItemPill} ...${covers[0]} plain />${covers.length > 1 && html`<span class="small soft">⇄ also on ${covers.slice(1).map(ref).join(", ")}</span>`}</span>`}</button>`;
  };
  const steward = list.filter((s) => s.agent && s.agent.started_by);
  const stewardWorking = steward.filter((s) => !s.agent.ended && !s.agent.idle).length;
  return html`${dialog}<main class="page wide"><${SessionTabs} tab="all" asks=${asks} /><div class="columns near">
    <nav class="sesslist" aria-labelledby="h-sessions">
      <h1 id="h-sessions">Running</h1>
      <span class="mono soft dotted" style="font-size: 12.5px">tmux -L glassine-hub</span>
      <div class="row" style="gap: 6px"><button onClick=${() => setCreating(true)}>＋ Plain shell</button>
        <a class="button plain" href=${hash("shells", { tab: "history" })}>Resume a past session</a></div>
      ${creating && html`<${NewShell} initial=${query.name && query.new ? query.name : ""} groups=${overview.data ? overview.data.groups : []} onCancel=${() => setCreating(false)} onDone=${async (n) => { setCreating(false); await reload(); setOpen(n); }} />`}
      <${Err} text=${error || act.error} />
      ${kept && html`<div class="notice quiet"><span>That session had work that isn't on GitHub, so its checkout stays at <code>${kept}</code>.</span></div>`}
      <${FamilyLegend} />
      <label class="row small" style="gap: 8px"><input type="checkbox" checked=${badgesOnly} onChange=${(e) => setBadgesOnly(e.target.checked)} /> Badges only</label>
      ${steward.length > 0 && html`<span class="small soft">Started by the Steward: ${stewardWorking} of 4 working.</span>`}
      ${RUN_GROUPS.map(([id, title]) => {
        const rows = list.filter((s) => runGroup(s) === id);
        return html`<section class="stack" style="gap: 8px" aria-label=${title}><h2 class="eyebrow" style="margin-top: 8px">${title} · ${rows.length}</h2>
          ${rows.length ? html`<div class=${badgesOnly ? "row" : "stack"} style="gap: ${badgesOnly ? 6 : 10}px">${rows.map(item)}</div>`
            : html`<p class="small soft">${id === "plain" ? "None open." : "None."}</p>`}</section>`;
      })}
      ${!list.some((s) => s.agent) && html`<p class="small soft">Start one from an issue, pull request or run under Work, or with "＋ New work".</p>`}
      ${(stopped.data || []).length > 0 && html`<h2 class="eyebrow" style="margin-top: 8px">Stopped</h2>
        ${stopped.data.map((s) => html`<div class="stack" style="gap: 4px; padding: 8px 0; border-top: 1px dotted var(--ink)">
          <span class="row" style="justify-content: space-between"><b class="mono" style="font-size: 13.5px; overflow-wrap: anywhere">${s.name}</b><span class="badge dim">stopped</span></span>
          <span class="soft" style="font-size: 13px">${s.agent.title} · ${whereFrom(s.agent)}${s.agent.started_by ? ` · started by ${s.agent.started_by}` : ""}</span>
          <span class="row" style="gap: 8px"><button disabled=${act.busy} onClick=${() => resume(s.name)}>Resume</button>
            <button class="plain" disabled=${act.busy} onClick=${() => setDiscarding(s.name)}>Discard…</button></span></div>`)}`}
    </nav>
    ${current ? html`<${SessionView} key=${current.name} session=${current} mode="full" asks=${asks} onClose=${() => setOpen(null)}
        onEnded=${(r) => { setKept(r && r.kept ? r.kept : null); setOpen(null); reloadAll(); }}
        onView=${reloadAll} onGone=${() => { setOpen(null); reload(); }}
        onResume=${() => confirm(
          { title: "Resume this session?", text: "Its conversation continues in a new terminal. The shell open here closes, with anything running in it.", label: "Resume" },
          () => resume(current.name),
        )} />`
      : html`<section class="termbox" aria-labelledby="h-term"><div class="empty" id="h-term">${list.length || (stopped.data || []).length ? "Choose a session." : "No sessions yet."}</div></section>`}
    ${discarding && html`<${Confirm} title=${`Discard ${discarding}?`} danger label="Discard"
      text="It can't be resumed after this. Its worktree goes, with anything uncommitted in it. Commits stay on the branch."
      onNo=${() => setDiscarding(null)} onYes=${() => { const name = discarding; setDiscarding(null);
        act.run(async () => { const r = await api(`shells/${encodeURIComponent(name)}?discard=1`, { method: "DELETE" }); if (r && r.ignored) setIgnoring({ name, ignored: r.ignored }); }); }} />`}
    ${ignoring && html`<${DiscardIgnored} item=${ignoring} onNo=${() => setIgnoring(null)} onYes=${() => { const name = ignoring.name; setIgnoring(null);
        act.run(() => api(`shells/${encodeURIComponent(name)}?discard=1&drop_ignored=1`, { method: "DELETE" })); }} />`}
  </div></main>`;
}

// --- frame --------------------------------------------------------------------------------------
function Login({ onIn }) {
  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const act = useAct();
  return html`<div class="login"><form class="keycap" onSubmit=${async (e) => {
      e.preventDefault();
      const r = await act.run(() => post("login", { user, password }));
      setPassword("");
      if (r) onIn();
    }}>
    <${Logo} /><h1>Sign in</h1>
    <p class="small soft">With your account on this computer.</p>
    <${Err} text=${act.error} />
    <label class="field"><span>User</span><input autocomplete="username" autofocus value=${user} onInput=${(e) => setUser(e.target.value)} /></label>
    <label class="field"><span>Password</span><input type="password" autocomplete="current-password" value=${password} onInput=${(e) => setPassword(e.target.value)} /></label>
    <button class="primary" disabled=${act.busy || !user || !password}>Sign in</button></form></div>`;
}

const Logo = () => html`<a class="logo" href="#/overview">
  <svg width="32" height="32" viewBox="0 0 32 32" aria-hidden="true"><rect x="3" y="3" width="18" height="22" rx="2" fill="none" stroke="currentColor" stroke-width="1.5" /><rect x="11" y="7" width="18" height="22" rx="2" fill="var(--mark)" stroke="var(--pen)" stroke-width="1.5" /></svg>
  <span><span class="eyebrow">GlassineOS Hub</span><small>GlassineOS/hub</small></span></a>`;

// The GitHub API budget, on Overview's stats line: the header's meter is the sessions' usage now (001 R1).
function ApiBudget() {
  const { data } = useLoad(() => api("limits"), [], 120000);
  if (!data) return null;
  const pct = data.limit ? Math.round(data.remaining / data.limit * 100) : 0;
  const reset = new Date(data.reset * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return html`<p class="budget" style="margin: -8px 0 18px"><b>GitHub API</b>
    <span class="bar ink" style="width: 64px; height: 8px" aria-hidden="true"><i style="width: ${pct}%"></i></span>
    ${data.remaining.toLocaleString()} of ${data.limit.toLocaleString()} left · resets ${reset}</p>`;
}

// How much of the sessions' usage allowance is used (001 FR-006): words and a bar, "low" from 80 %. hubd reads it
// from the sessions' status lines; with no rate limit and no allowance set it says it doesn't know.
// A reset on another day names the day, so a seven-day window days away doesn't read as later today.
const resetWords = (r) => {
  if (typeof r !== "number") return String(r);
  const at = new Date(r * 1000);
  const time = at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return at.toDateString() === new Date().toDateString() ? time : `${at.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" })} ${time}`;
};
function UsageMeter() {
  const { data, error } = useLoad(() => api("usage"), [], 60000);
  const u = data || { known: false, says: error ? "usage can't be read" : "usage not known" };
  const label = `Usage: ${u.says}${u.known && u.resets ? `, resets ${resetWords(u.resets)}` : ""}`;
  const pct = u.known ? Math.round(u.used * 100) : 0;
  return html`<span class="budget usage ${u.low ? "low" : ""}" role="img" aria-label=${label} title=${label}><b>Usage</b>
    <span class="bar ink" style="width: 48px; height: 8px"><i style="width: ${pct}%"></i></span>
    ${u.known ? `${pct}%${u.low ? " · low" : ""}` : "not known"}</span>`;
}

// --- the device lock, on Overview (007 FR-003, 007 R1) ---------------------------------------------------
// In words from the devices' own reports, which anything on the socket can send: never a bare free or held.
function DeviceCard({ asks }) {
  const { data, error } = useLoad(() => api("device"), [], 15000);
  const holding = asks.decisions.holding;
  const goes = asks.interactions.grants.filter((g) => g.detail.kind === "go");
  return html`<section class="panel stack" style="gap: 10px; padding: 18px" aria-labelledby="h-device">
    <h2 id="h-device" class="eyebrow">Device</h2>
    ${error && html`<p class="small" role="alert">The hub can't read the device reports (${error}). <span class="mono">dev status</span> asks the device itself.</p>`}
    ${data && data.devices.map((d) => html`<div class="stack" style="gap: 4px" key=${d.device || "none"}>
      ${d.device && html`<h3 class="mono" style="font-size: 14px">${d.device}</h3>`}
      ${d.lines.map((line) => html`<p class="small" style="overflow-wrap: anywhere">${line}.</p>`)}</div>`)}
    ${holding && html`<p class="small" style="font-weight: ${holding.holding ? 600 : 400}">${holding.holding ? `You hold it: ${holding.words}` : holding.words}</p>`}
    <p class="small">${goes.length ? html`${count(goes.length, "go")} in force: ${goes.map((g, i) => html`${i ? "; " : ""}${g.detail.says}`)}. ` : "No go in force. "}
      <button class="link" onClick=${() => needsYou({ filter: "grants" })}>Active grants</button></p>
    ${data && html`<p class="small soft">${data.only}</p>`}
  </section>`;
}

const GO_ACTIONS = ["reboot", "suspend", "load-test", "close-apps", "eye-test"];

function GoForm({ devices, onDone, onCancel }) {
  const sessions = useSessions();
  const [words, setWords] = useState("");
  const [actions, setActions] = useState(new Set());
  const [other, setOther] = useState("");
  const [session, setSession] = useState("any");
  const [device, setDevice] = useState("any");
  const [unit, setUnit] = useState("runs");
  const [amount, setAmount] = useState(1);
  const act = useAct(onDone);
  const named = [...actions, ...other.split(",").map((a) => a.trim()).filter(Boolean)];
  const toggle = (a) => { const next = new Set(actions); if (next.has(a)) next.delete(a); else next.add(a); setActions(next); };
  const ready = words.trim() && named.length > 0 && Number(amount) > 0;
  const send = () => act.run(() => post("decisions", { kind: "go", words, scope: { actions: named, session, device }, ends: { [unit]: Number(amount) } }));
  return html`<div class="stack" style="gap: 10px" role="group" aria-label="Record a go">
    <label class="stack" style="gap: 4px; font-size: 14px; font-weight: 500">What you're allowing, in your words
      <textarea rows="2" value=${words} onInput=${(e) => setWords(e.target.value)}></textarea></label>
    <fieldset class="row" style="gap: 6px 14px; border: 0; padding: 0"><legend class="small soft">Actions it covers</legend>
      ${GO_ACTIONS.map((a) => html`<label class="row small" style="gap: 6px"><input type="checkbox" checked=${actions.has(a)} onChange=${() => toggle(a)} /> ${a}</label>`)}
      <label class="row small" style="gap: 6px">Others <input class="mono" value=${other} placeholder="comma between" onInput=${(e) => setOther(e.target.value)} /></label></fieldset>
    <div class="row" style="gap: 8px 14px">
      <label class="row small" style="gap: 6px">Session <select value=${session} onChange=${(e) => setSession(e.target.value)}><option value="any">any session</option>${(sessions.data || []).map((s) => html`<option value=${s.name}>${s.name}</option>`)}</select></label>
      <label class="row small" style="gap: 6px">Device <select value=${device} onChange=${(e) => setDevice(e.target.value)}><option value="any">any device</option>${devices.map((d) => html`<option value=${d}>${d}</option>`)}</select></label>
      <label class="row small" style="gap: 6px">Ends after <input type="number" min="1" style="width: 5em" value=${amount} onInput=${(e) => setAmount(e.target.value)} />
        <select aria-label="Runs or hours" value=${unit} onChange=${(e) => setUnit(e.target.value)}><option value="runs">runs</option><option value="hours">hours</option></select></label></div>
    <${Err} text=${act.error} />
    <div class="row" style="gap: 8px"><button class="primary" disabled=${act.busy || !ready} onClick=${send}>Record this go</button><button class="plain" onClick=${onCancel}>Cancel</button></div>
  </div>`;
}

// A go for the device, and "I've got the device", in Needs you. Both are yours: the ops are behind the login, and no tool makes one.
function GoPanel({ asks }) {
  const device = useLoad(() => api("device").catch(() => ({ devices: [] })), []);
  const [form, setForm] = useState(false);
  const [note, setNote] = useState(null);
  const act = useAct(asks.decisions.reload);
  const holding = asks.decisions.holding;
  const hold = (on) => act.run(async () => { const r = await post("device/holding", { holding: on }); setNote(on ? `${count(r.ended, "device go")} ended.` : null); });
  return html`<section class="stack" style="gap: 10px" aria-labelledby="h-go"><h2 id="h-go" class="eyebrow">The device</h2>
    <${Err} text=${act.error} />
    ${holding && html`<p role="status">${holding.words}${note ? ` ${note}` : ""}</p>`}
    <div class="row" style="gap: 8px">
      ${!form && html`<button onClick=${() => setForm(true)}>Record a go…</button>`}
      ${holding && (holding.holding
        ? html`<button disabled=${act.busy} onClick=${() => hold(false)}>Done</button>`
        : html`<button disabled=${act.busy} onClick=${() => hold(true)}>I've got the device</button>`)}
      <span class="small soft">Ends every device go but an eye test, and refuses a take that names actions until you press Done. It can't stop a running command.</span></div>
    ${form && html`<${GoForm} devices=${(device.data ? device.data.devices : []).map((d) => d.device).filter(Boolean)} onDone=${() => { setForm(false); return asks.decisions.reload(); }} onCancel=${() => setForm(false)} />`}
  </section>`;
}

// --- the queue view: it reads, and approving records your decision. It merges nothing ------------
function QueueRow({ r, onChanged }) {
  const act = useAct(onChanged);
  const a = r.approval;
  const open = r.state === "OPEN";
  const said = "Approved on the queue page.";
  const approve = () => act.run(() => (a.asked
    ? post(`decisions/${a.asked}/approve`, { words: said })
    : post("decisions", { kind: "merge", words: said, scope: { repo: r.repo, number: r.number, head: r.head } })));
  return html`<article class="stack" style="gap: 6px; padding: 10px 0; border-bottom: 1px solid var(--rule)" aria-label=${`${r.repo}#${r.number}`}>
    <div class="row" style="gap: 8px">
      ${r.order && html`<span class="mono small">${r.order.n} of ${r.order.m}</span>`}
      ${r.next && html`<span class="badge mark">Next</span>`}
      ${!open && html`<span class="badge dim">${r.state === "MERGED" ? (r.merged_on ? `Merged ${r.merged_on}` : "Merged") : r.state}</span>`}
      ${r.draft && html`<span class="badge dim">Draft</span>`}
      ${r.blockers.length > 0 && html`<span class="badge bad">Blocked</span>`}
      <a class="mono small" href=${hash("work", { tab: "prs", repo: r.repo, item: r.number })}>${r.repo}#${r.number}</a>
      <span style="overflow-wrap: anywhere">${r.title}</span></div>
    ${open && html`<dl class="defs">
      <dt>Head</dt><dd><span class="mono" style="font-size: 13px">${r.head ? r.head.slice(0, 12) : "not known"}</span> <span class="small soft" style="overflow-wrap: anywhere">${r.branch} into ${r.base}, by ${r.author}</span></dd>
      <dt>Tested</dt><dd style="overflow-wrap: anywhere">${r.tested}</dd>
      <dt>Checks</dt><dd>${r.checks}. ${r.mergeable}.</dd>
      <dt>Your approval</dt><dd style="overflow-wrap: anywhere">${a.says}${a.notes.map((n) => html`<div class="small soft">${n}</div>`)}</dd>
      <dt>GitHub's reviews</dt><dd>${r.reviews}. <span class="small soft">Not your approval, and it counts for nothing here.</span></dd>
      ${r.blockers.length > 0 && html`<dt>Blockers</dt><dd>${r.blockers.map((b) => html`<div style="overflow-wrap: anywhere"><a class="mono small" href=${hash("work", { tab: "issues", repo: b.repo, item: b.number })}>${b.repo}#${b.number}</a> ${b.title}</div>`)}</dd>`}
      ${r.fixes.length > 0 && html`<dt>It says it fixes</dt><dd>${r.fixes.map((b) => html`<div style="overflow-wrap: anywhere"><a class="mono small" href=${hash("work", { tab: "issues", repo: b.repo, item: b.number })}>${b.repo}#${b.number}</a> ${b.title}</div>`)}</dd>`}</dl>`}
    ${open && a.state === "none" && r.head && html`<div class="row" style="gap: 8px">
      <button class="primary" disabled=${act.busy} onClick=${approve}>Approve ${r.head.slice(0, 7)}</button>
      ${a.asked && html`<button disabled=${act.busy} onClick=${() => act.run(() => post(`decisions/${a.asked}/deny`, { why: null }))}>Say no</button>`}</div>`}
    ${open && a.state === "approved" && html`<div class="row"><button disabled=${act.busy} onClick=${() => act.run(() => post(`decisions/${a.id}/end`, { why: "taken back on the queue page" }))}>Take it back</button></div>`}
    <${Err} text=${act.error} /></article>`;
}

const WORK_TABS = [["issues", "Issues"], ["prs", "Pull requests"], ["actions", "Actions"], ["queue", "Queue"]];

function WorkQueue() {
  const { data, error, reload } = useLoad(() => api("queue"), [], 15000);
  const row = (r) => html`<${QueueRow} key=${`${r.repo}#${r.number}`} r=${r} onChanged=${reload} />`;
  const blocker = (b) => html`<div class="stack tight" key=${`${b.repo}#${b.number}`} style="padding: 6px 0">
    <div><a class="mono small" href=${hash("work", { tab: "issues", repo: b.repo, item: b.number })}>${b.repo}#${b.number}</a> <span style="overflow-wrap: anywhere">${b.title}</span>${b.linked ? "" : html` <span class="small soft">No open pull request links to it.</span>`}</div>
    ${b.why && html`<span class="small soft" style="overflow-wrap: anywhere">${b.why}</span>`}</div>`;
  return html`<main class="page close" aria-labelledby="h-queue">
    <h1 class="sr">Work</h1>
    <div role="tablist" aria-label="Work type" class="tabs">
      ${WORK_TABS.map(([id, label]) => html`<a role="tab" aria-selected=${id === "queue" ? "true" : "false"} href=${hash("work", { tab: id })}>${label}</a>`)}</div>
    <div class="stack tight"><h2 id="h-queue" style="font-size: 21px; font-weight: 600">Queue</h2>
      <span class="small soft">Open pull requests by set and order, from the work store. This page merges, reviews and starts nothing. Approving records your decision for the head shown, which is what lets a session merge it; "Set:" and "Tested:" are what each pull request's text says, and nothing checks them.</span></div>
    <${Err} text=${error} />
    ${data && !data.ready && html`<p role="status">${data.says}</p>`}
    ${data && data.ready && html`<p class="small soft" role="status">Last synced ${ago(data.synced_at * 1000)}. Approving asks GitHub for the head at that moment.</p>
      ${data.blockers.length > 0 && html`<section class="stack" style="gap: 4px"><h3 style="font-size: 15px">Blockers (${data.blockers.length})</h3>${data.blockers.map(blocker)}</section>`}
      ${data.sets.map((s) => html`<section class="stack" style="gap: 4px" key=${s.name}><h3 style="font-size: 15px">Set <span class="mono">${s.name}</span></h3>
        ${s.problems.map((p) => html`<p class="small" style="overflow-wrap: anywhere">${p}</p>`)}
        ${s.rows.map(row)}</section>`)}
      ${data.alone.length > 0 && html`<section class="stack" style="gap: 4px"><h3 style="font-size: 15px">On their own (${data.alone.length})</h3>${data.alone.map(row)}</section>`}
      ${!data.sets.length && !data.alone.length && html`<p class="small soft">No open pull requests.</p>`}`}
  </main>`;
}

// --- the Notes page ------------------------------------------------------------------------------
const NOTE_BADGE = { current: "", open: "mark", history: "dim", retracted: "bad", "archive, unreviewed": "dim" };
const NOTES_MOST = 100; // hubd's limit

function NotesPage() {
  const { data, error } = useLoad(() => api("notes"), [], 60000);
  const [words, setWords] = useState(""); // never in the address, which the Steward's panel reads
  const [found, setFound] = useState(null);
  const [searched, setSearched] = useState("");
  const act = useAct();
  // Rows from an earlier search never stay under new words, and "show more" means more of what was searched.
  const search = (asked, limit) => act.run(async () => { setFound(null); setSearched(asked); setFound(await post("notes/find", { words: asked, limit })); });
  const said = found && !found.here ? found.says : data && !data.here ? data.says : null;
  return html`<main class="page close" aria-labelledby="h-notes">
    <div class="stack tight"><h1 id="h-notes">Notes</h1>
      <span class="small soft">The same search as <span class="mono">notes find</span>, by word. Only a login reads this: no session's token can, and the Steward has no tool for it. Every row says what it is, and current comes first.</span></div>
    <${Err} text=${error || act.error} />
    ${said && html`<p role="status" style="overflow-wrap: anywhere">${said}</p>`}
    <form class="row" style="gap: 8px" role="search" onSubmit=${(e) => { e.preventDefault(); if (words.trim()) search(words); }}>
      <label class="row small" style="gap: 6px; flex: 1">Look for
        <input type="search" style="flex: 1; min-width: 0" maxlength="500" value=${words} onInput=${(e) => setWords(e.target.value)} /></label>
      <button class="primary" type="submit" disabled=${act.busy || !words.trim()}>${act.busy ? "Searching…" : "Search"}</button></form>
    ${found && found.here && html`<div class="stack" style="gap: 4px">
      <p role="status" class="small">${found.says}${found.total > found.rows.length ? `, showing ${found.rows.length}` : ""}.</p>
      ${found.warnings.map((w) => html`<p class="small" style="overflow-wrap: anywhere">${w}</p>`)}
      ${found.rows.map((r) => html`<article class="stack" style="gap: 4px; padding: 10px 0; border-bottom: 1px solid var(--rule)" aria-label=${`${r.state}: ${r.where}`}>
        <div class="row" style="gap: 8px"><span class="badge ${NOTE_BADGE[r.state] ?? "bad"}">${r.state}</span>
          <span class="mono small" style="overflow-wrap: anywhere">${r.where}</span>${r.label && html`<span class="mono small soft" style="overflow-wrap: anywhere">${r.label}</span>`}</div>
        <p style="overflow-wrap: anywhere">${r.text}</p></article>`)}
      ${found.total > found.rows.length && found.rows.length < NOTES_MOST && html`<div class="row"><button disabled=${act.busy} onClick=${() => search(searched, NOTES_MOST)}>Show up to ${NOTES_MOST}</button></div>`}
      ${found.total > found.rows.length && found.rows.length >= NOTES_MOST && html`<p class="small soft">That's as many as this page shows. Narrow the words, or use <span class="mono">notes find --limit</span> in a terminal.</p>`}</div>`}
  </main>`;
}

// 001 FR-001. Knowledge is the docs search until PR 15, Notes the notes search until PR 16. Device is on Overview,
// decisions are in Needs you; their old addresses go there (Hub's MOVED).
const NAV = [["overview", "Overview"], ["roadmap", "Roadmap"], ["work", "Work"], ["knowledge", "Knowledge"], ["notes", "Notes"], ["shells", "Sessions"]];

// --- the Steward ---------------------------------------------------------------------------------
const STEWARD = "steward";
const SEEN_KIND = { issues: "issue", prs: "pull request", actions: "run" };
const SEEN_SCREEN = { overview: "Overview", roadmap: "Roadmap", work: "Work", knowledge: "Knowledge", notes: "Notes", shells: "Sessions" };
const STATE_BADGE = { "Waiting for you": "mark", Stopped: "dim", "Not started": "dim" };

// Old addresses and where they live now. Work's tabs had their own pages once; Docs held the notes as a tab;
// Device is a card on Overview.
const OLD_WORK_PAGES = new Set(["issues", "prs", "actions", "queue"]);
function movedRoute(route) {
  const q = route.query;
  if (OLD_WORK_PAGES.has(route.path)) return { path: "work", query: { ...q, tab: route.path }, moved: false };
  if (route.path === "docs") return { path: q.tab === "notes" ? "notes" : "knowledge", query: {}, moved: true };
  if (route.path === "device") return { path: "overview", query: {}, moved: true };
  // The advanced launch page is gone: Launch opens over the item.
  if (route.path === "launch") {
    const tab = { pr: "prs", run: "actions" }[String(q.action || "").split("-")[0]] || "issues";
    return q.repo && q.number ? { path: "work", query: { tab, at: q.repo, item: q.number }, moved: true, to: hash("work", { tab, at: q.repo, item: q.number }) } : { path: "work", query: {}, moved: true };
  }
  return { path: route.path, query: q, moved: false };
}

function seenFrom(route) {
  const q = route.query;
  const moved = movedRoute(route);
  const path = moved.path, tab = path === "work" ? moved.query.tab || "issues" : path;
  // From the address, which a link can fill with anything. Same pattern as hubd's.
  const item = (repo, n) => (/^[A-Za-z0-9._-]+$/.test(repo || "") && /^[0-9]+$/.test(n || "") ? `${repo}#${n}` : null);
  if (path === "work" && item(q.at || q.repo, q.item)) return { screen: "Work", kind: SEEN_KIND[tab] || null, selection: item(q.at || q.repo, q.item) };
  if (path === "work" && tab === "queue") return { screen: "Queue", kind: null, selection: null };
  return { screen: SEEN_SCREEN[path] || "Overview", kind: null, selection: null };
}

function keptRail() {
  try { return localStorage.getItem("steward-rail") !== "open"; } catch { return true; }
}

function StewardSession({ state, seen, buttons, reload, asks }) {
  const act = useAct(reload);
  const words = state.state;
  const running = words !== "Not started" && words !== "Stopped";
  if (!running) {
    return html`<div class="stack" style="gap: 12px; padding: 14px">
      <p style="font-size: 14.5px">${words === "Stopped" ? "The session has stopped. Resuming continues the same conversation." : "One long-lived session for the whole project. Every write it tries asks you first, on a card."}</p>
      <${Err} text=${act.error} />
      <button class="primary" style="align-self: flex-start" disabled=${act.busy} onClick=${() => act.run(() => (words === "Stopped" ? post("agents/resume", { name: STEWARD }) : post("agents/run", { action: "project-steward" })))}>${act.busy ? "Starting…" : words === "Stopped" ? "Resume the Steward" : "Start the Steward"}</button></div>`;
  }
  const offers = asks.work.items.filter((i) => i.by === STEWARD && nwWaits(i));
  // The panel's head has the Steward's name, model and state: below it is the compact SessionView (004 FR-001).
  const session = { name: STEWARD, attached: 0, agent: { persona: STEWARD, persona_name: "Steward", waiting: words === "Waiting for you", idle: words === "Idle", ended: false } };
  return html`<${SessionView} session=${session} mode="compact" asks=${asks} seen=${seen} buttons=${buttons} queued=${state.queued} onGone=${reload}>
    ${offers.length > 0 && html`<div class="dock-asks stack" style="gap: 8px"><span class="eyebrow">Waiting for you</span>${offers.map((i) => html`<${WorkWaiting} key=${i.id} item=${i} compact reload=${asks.reload} />`)}</div>`}
    <${Err} text=${state.lost} /><//>`;
}

function StewardModel({ running, current, open }) {
  const { data, reload } = useLoad(() => post("agents/steward"), []);
  const act = useAct(reload);
  if (!data || !open) return null;
  const later = running && current && current !== data.model;
  const name = (m) => NW_MODEL[m] || m;
  return html`<div class="stack tight dock-model"><span id="dock-sm" class="eyebrow">Steward model</span>
    <div role="radiogroup" aria-labelledby="dock-sm" class="seg" style="align-self: flex-start">${data.models.map((m) => html`<button role="radio" aria-checked=${data.model === m ? "true" : "false"} disabled=${act.busy} onClick=${() => act.run(() => post("agents/steward", { model: m }))}>${name(m)}${m === "sonnet" ? " · default" : ""}</button>`)}</div>
    <span class="small soft">${later ? `Running on ${name(current)} now. ${name(data.model)} takes over the next time it starts or resumes.` : "Sonnet by default. A change takes effect the next time it starts or resumes."}</span>
    <${Err} text=${act.error} /></div>`;
}

function Steward({ route, asks }) {
  const [rail, setRailState] = useState(keptRail);
  const [modelOpen, setModelOpen] = useState(false);
  const setRail = (next) => { setRailState(next); try { localStorage.setItem("steward-rail", next ? "rail" : "open"); } catch { /* it only helps */ } };
  const { data: loaded, reload } = useLoad(() => post("agents/state", { name: STEWARD }), [], rail ? 15000 : 3000);
  // A failed read keeps what we knew, or a brief hubd error would close the terminal and offer Start.
  const known = useRef(null);
  if (loaded) known.current = loaded;
  const state = known.current;
  const { data: buttons } = useLoad(() => post("agents/buttons").then((r) => r.buttons).catch(() => []), []);
  const seen = seenFrom(route);
  const words = state ? state.state : "Not started";
  const running = words !== "Not started" && words !== "Stopped";
  useEffect(() => { if (running) post("agents/context", { name: STEWARD, ...seen }).catch(() => {}); }, [running, seen.screen, seen.kind, seen.selection]);
  const asking = asks.open.filter((a) => a.session === STEWARD).length + asks.work.items.filter((i) => i.by === STEWARD && nwWaits(i)).length;
  const planFromSteward = () => launch({ steward: true, repos: seen.selection ? [seen.selection.split("#")[0]] : undefined, context: seen.selection || undefined,
    pins: seen.selection ? [{ kind: "ref", label: seen.selection }] : undefined, from: { view: seen.screen, ref: seen.selection || null } });
  if (rail) {
    return html`<nav class="dock-rail" aria-label="Steward">
      <button class="dock-s" aria-label=${`Open the Steward, ${words}${asking ? `, ${count(asking, "question")} for you` : ""}`} title=${`Steward: ${words}`} onClick=${() => setRail(false)}>S${asking > 0 && html`<span class="dock-count">${asking}</span>`}</button>
      <button class="dock-item" aria-label="Plan new work with the Steward" title="Plan new work with the Steward" onClick=${planFromSteward}>＋</button></nav>`;
  }
  return html`<aside class="dock" aria-labelledby="dock-h">
    <div class="dock-head"><span class="dock-s small" aria-hidden="true">S</span>
      <span class="stack" style="gap: 0; flex: 1; min-width: 0"><h2 id="dock-h" style="font-size: 17px; font-weight: 600">Steward</h2>
        <button class="link dock-modelname mono" aria-expanded=${modelOpen ? "true" : "false"} aria-label=${`Steward model${state && state.model ? `: ${state.model}` : ""}. Change`} onClick=${() => setModelOpen(!modelOpen)}>${(state && state.model) || "model"}</button></span>
      <span class="badge ${STATE_BADGE[words] || ""}">${words}</span>
      <button class="square" aria-label="Plan new work with the Steward" title="Plan new work with the Steward" onClick=${planFromSteward}>＋</button>
      <button class="square" aria-label="Collapse the Steward to a rail" onClick=${() => setRail(true)}>›</button></div>
    <${StewardModel} running=${running} current=${state && state.model} open=${modelOpen} />
    <div class="dock-sees"><${Eyebrow} soft>Sees<//><span class="label" style="padding-right: 8px">${seen.screen}</span>${seen.selection && html`<span class="label mono" style="padding-right: 8px">${seen.selection}</span>`}</div>
    <${StewardSession} state=${state || { state: "Not started", queued: 0 }} seen=${seen} buttons=${buttons} reload=${reload} asks=${asks} />
    <p class="small soft" style="margin: 0; padding: 0 12px 12px">A configured session like any other: no shell, reads everything, and every write asks you first.</p>
  </aside>`;
}

function App() {
  const [state, setState] = useState({ checking: true });
  const route = useRoute();
  const check = useCallback(async () => {
    try {
      setState({ host: await api("host") });
    } catch (e) {
      setState(e.status === 401 ? { out: true } : { fatal: e.message });
    }
  }, []);
  useEffect(() => {
    check();
    const out = () => setState({ out: true });
    window.addEventListener("hub-logout", out);
    return () => window.removeEventListener("hub-logout", out);
  }, []);
  if (state.checking) return null;
  if (state.out) return html`<${Login} onIn=${check} />`;
  if (state.fatal) return html`<div class="login"><div class="error">${state.fatal}</div></div>`;
  return html`<${Hub} host=${state.host} route=${route} onOut=${() => setState({ out: true })} />`;
}

function Hub({ host: first, route, onOut }) {
  // 001 FR-005, 001 FR-020: who you are and which hubd, read again every 15 s; when it or the list fails, the page says so.
  const hostPoll = useLoad(() => api("host"), [], 15000);
  const knownHost = useRef(first);
  if (hostPoll.data) knownHost.current = hostPoll.data;
  const host = knownHost.current;
  HOST_USER = host.user || "";
  // One list of what waits for you: asks, decisions and new work (interaction.list), every 3 s (003 SC-002).
  const listed = useLoad(() => api("interactions"), [], 3000);
  // A failed read keeps what we knew, or a brief hubd error would close the cards you're filling in.
  const known = useRef({ items: [], grants: [], counts: { pending: 0, blocking: 0, by_kind: {}, longest_wait: 0 }, holding: null });
  if (listed.data) known.current = listed.data;
  // Launch records (005 R1): what LaunchModal draws its stage from, and SetAside reads.
  const planned = useLoad(() => api("new-work"), [], 3000);
  const knownWork = useRef({ templates: [], items: [] });
  if (planned.data) knownWork.current = planned.data;
  const reloadAll = () => { listed.reload(); return planned.reload(); };
  const inter = known.current;
  const isAsk = (r) => r.kind === "permission" || r.kind === "question";
  // The shape the Steward panel and Sessions read: the asks themselves, and the decisions as hubd describes them.
  const asks = { open: inter.items.filter((r) => isAsk(r) && r.status === "pending").map((r) => r.detail),
    answered: inter.items.filter((r) => isAsk(r) && r.status !== "pending").map((r) => r.detail),
    work: knownWork.current, reload: reloadAll, interactions: inter, stale: Boolean(listed.error),
    decisions: { items: [...inter.items, ...inter.grants].filter((r) => r.kind === "decision").map((r) => r.detail), holding: inter.holding, reload: listed.reload, error: listed.error } };
  asks.waiting = inter.counts.pending;
  const [needs, setNeeds] = useState(null); // the Needs you modal, and what had focus when it opened

  const [launching, setLaunching] = useState(null);
  const [behind, setBehind] = useState(null); // a Launch sent to the background (005 FR-008)
  useEffect(() => {
    const show = (e) => { setBehind(null); setLaunching({ ...e.detail, key: Date.now() }); };
    const openNeeds = (e) => setNeeds({ ...e.detail, key: Date.now(), opener: document.activeElement });
    window.addEventListener("hub-launch", show);
    window.addEventListener("hub-needs-you", openNeeds);
    return () => { window.removeEventListener("hub-launch", show); window.removeEventListener("hub-needs-you", openNeeds); };
  }, []);
  // The old addresses of Needs you, Active and the Decisions page open the modal with the matching filter.
  const oldNeeds = route.path === "decisions" ? "decisions" : route.path === "shells" && route.query.tab === "needs" ? "all" : route.path === "shells" && route.query.tab === "active" ? "grants" : null;
  useEffect(() => {
    if (!oldNeeds) return;
    needsYou({ filter: oldNeeds });
    history.replaceState(null, "", route.path === "decisions" ? hash("overview") : hash("shells", { tab: "all" }));
  }, [oldNeeds]);
  // Focus goes back where it was; if that's gone, to the header's Needs you button.
  const closeNeeds = () => {
    const back = needs && needs.opener;
    setNeeds(null);
    const to = back && back.isConnected && back !== document.body ? back : document.querySelector("header.top .needs-open");
    if (to) to.focus();
  };
  // Links from before Work was one page, the Docs and Device pages, and the items a card points to.
  const { path, query, moved, to } = movedRoute(route);
  useEffect(() => { if (moved) history.replaceState(null, "", to || hash(path)); }, [route.path, route.query.tab]);
  const views = { overview: Overview, roadmap: Roadmap, work: Work, knowledge: Knowledge, notes: NotesPage, shells: Sessions };
  const View = views[path] || Overview;
  const here = path;
  const unreachable = Boolean(hostPoll.error || listed.error);
  return html`<div class="with-dock"><div class="dock-main">
    <header class="top"><${Logo} />
      <nav aria-label="Primary">${NAV.map(([key, label]) => html`<a href=${key === "shells" ? hash("shells", { tab: "all" }) : `#/${key}`} aria-current=${here === key ? "page" : null}>${label}</a>`)}</nav>
      <div class="end">
        <${NeedsButton} asks=${asks} />
        <button class="primary new-work" onClick=${() => launch({ from: { view: SEEN_SCREEN[here] || "Overview" } })}>＋ New work</button>
        ${!host.gh && html`<span class="badge bad">no gh on the host</span>`}
        ${!host.tmux && html`<span class="badge bad">no tmux on the host</span>`}
        <${UsageMeter} />
        <span class="small whoami"><span class="mono">${host.user}</span>${host.hubd && html` · <span class="soft">hubd</span> <span class="mono soft">${host.hubd}</span>`}</span>
        <button class="plain" onClick=${async () => { await post("logout"); onOut(); }}>Sign out</button>
      </div></header>
    ${unreachable && html`<div class="unreachable" role="status">hubd can't be reached — showing what was last read.</div>`}
    <${View} key=${path + JSON.stringify(path === "shells" || path === "work" ? {} : query)} query=${query} asks=${asks} /></div>
    <${Steward} route=${route} asks=${asks} />
    ${launching && html`<${LaunchModal} key=${launching.key} open=${launching} work=${asks.work} asks=${asks} reload=${reloadAll}
      onClose=${() => setLaunching(null)} onBehind=${(b) => { setLaunching(null); setBehind(b); }} />`}
    ${needs && html`<${NeedsYouModal} key=${needs.key} initial=${needs} data=${inter} asks=${asks} onClose=${closeNeeds} />`}
    ${behind && html`<div role="status" class="nw-toast"><span style="flex: 1">${behind.name ? html`<a class="mono" style="font-weight: 600" href=${hash("shells", { tab: "all", name: behind.name })} onClick=${() => setBehind(null)}>${behind.name}</a>` : html`<b>${behind.title}</b>`} goes on in the background. Its asks and its result arrive in <button class="link" onClick=${() => needsYou()}>Needs you</button>.</span>
      <button class="plain" onClick=${() => launch({ id: behind.id })}>Reopen</button><button class="square" aria-label="Dismiss" onClick=${() => setBehind(null)}>×</button></div>`}</div>`;
}

render(html`<${App} />`, document.getElementById("root"));
