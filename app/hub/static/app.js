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

// 001 FR-007–FR-010: at 760 px or less the header folds into Menu and the Steward into a floating button. The same
// width as the one phone block in style.css.
const PHONE = "(max-width: 760px)";
function usePhone() {
  const query = typeof window.matchMedia === "function" ? window.matchMedia(PHONE) : null;
  const [phone, setPhone] = useState(() => Boolean(query && query.matches));
  useEffect(() => {
    if (!query || !query.addEventListener) return undefined;
    const on = () => setPhone(Boolean(query.matches));
    query.addEventListener("change", on);
    return () => query.removeEventListener("change", on);
  }, []);
  return phone;
}

// A sheet's open state (the Menu, the Steward): it is closed when the view changes and when the width leaves phone width.
// A sheet that is no longer drawn fires no close event, so without this it would reopen by itself when the width came back.
function useSheet(view, phone) {
  const [sheet, setSheet] = useState(null);
  useEffect(() => setSheet(null), [view, phone]);
  return [sheet, setSheet];
}

// 001 FR-018: no blinking cursor when the viewer asks for reduced motion (and an e-ink browser isn't asked to repaint it).
const reducedMotion = () => typeof window.matchMedia === "function" && Boolean(window.matchMedia("(prefers-reduced-motion: reduce)").matches);

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

// 001 FR-016: every modal and sheet opens with showModal, so Esc closes it and the page behind it is inert, and Tab and
// Shift+Tab go round inside it instead of out to the browser. A dialog opened inside another one keeps its own Tab.
const FOCUSABLE = 'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, [tabindex]:not([tabindex="-1"])';
function trapTab(e) {
  const d = e.currentTarget;
  if (e.key !== "Tab" || e.defaultPrevented || e.target.closest("dialog") !== d) return;
  const all = [...d.querySelectorAll(FOCUSABLE)].filter((x) => x.closest("dialog") === d && x.getClientRects().length > 0);
  if (!all.length) return;
  const wrap = trapWrap(e.shiftKey, document.activeElement, d, all);
  if (wrap) { e.preventDefault(); wrap.focus(); }
}
// Where Tab or Shift+Tab has to be held and sent: the control to focus, or null to let the browser move on. The dialog
// itself counts as outside the list (it holds focus when its control went away), so Shift+Tab from it goes to the last.
function trapWrap(shift, at, d, all) {
  const first = all[0], last = all[all.length - 1];
  if (shift && (at === d || at === first || !d.contains(at))) return last;
  if (!shift && (at === d || at === last || !d.contains(at))) return first;
  return null;
}
// The control before or after `from`, inside its dialog if it is in one: how F6 leaves a terminal.
function focusPast(from, step) {
  if (!from) return;
  const scope = from.closest("dialog[open]") || document;
  const inside = (x) => (scope === document ? !x.closest("dialog") : x.closest("dialog") === scope);
  const all = [...scope.querySelectorAll(FOCUSABLE)].filter((x) => inside(x) && x.getClientRects().length > 0);
  const box = from.closest(".xterm") || from;
  const next = pickPast(all.filter((x) => !box.contains(x)), box, step);
  if (next) next.focus();
}
// Of the controls outside `box`, in page order: the nearest after it (step > 0) or before it, and when there is none that
// way, the one at the other end, so F6 and Shift+F6 go round instead of stopping at the last or first control.
function pickPast(outside, box, step) {
  const after = outside.filter((x) => box.compareDocumentPosition(x) & Node.DOCUMENT_POSITION_FOLLOWING);
  const before = outside.filter((x) => box.compareDocumentPosition(x) & Node.DOCUMENT_POSITION_PRECEDING);
  if (step > 0) return after[0] || before[0];
  return before[before.length - 1] || after[after.length - 1];
}
// The open modals, last opened on top. When the control that had focus goes (an answered card, a stage that moved on),
// focus goes to the top dialog itself rather than to the page, so the keyboard and a screen reader keep their place.
const MODALS = [];
const focusLost = () => !document.activeElement || document.activeElement === document.body;
function useModal(ref) {
  useEffect(() => {
    const d = ref.current, opener = document.activeElement;
    d.tabIndex = -1;
    d.showModal();
    MODALS.push(d);
    d.addEventListener("keydown", trapTab);
    const watch = new MutationObserver(() => { if (MODALS[MODALS.length - 1] === d && focusLost()) d.focus(); });
    watch.observe(d, { childList: true, subtree: true });
    return () => {
      watch.disconnect();
      d.removeEventListener("keydown", trapTab);
      MODALS.splice(MODALS.indexOf(d), 1);
      // Back to what opened it, or else to the dialog under it.
      setTimeout(() => {
        if (!focusLost()) return;
        const top = MODALS[MODALS.length - 1];
        const back = opener && opener.isConnected && opener !== document.body && (!top || top.contains(opener)) ? opener : top;
        if (back) back.focus();
      }, 0);
    };
  }, []);
}

const Err = ({ text }) => (text ? html`<div class="error" role="alert">${text}</div>` : null);
const Eyebrow = ({ children, soft }) => html`<span class="eyebrow ${soft ? "soft" : ""}">${children}</span>`;

function Confirm({ title, text, label, danger, onYes, onNo }) {
  const ref = useRef();
  useModal(ref);
  return html`<dialog ref=${ref} aria-label=${title} onClose=${onNo}>
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
    return html`<svg width="16" height="16" viewBox="0 0 16 16" ...${a}><rect x="2" y="2" width="12" height="12" rx="2" fill="var(--accent-2)" stroke=${ink} stroke-width="1.5" /><path d="M5.5 5.5l5 5M10.5 5.5l-5 5" stroke="var(--paper)" stroke-width="1.5" /></svg>`;
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
  const chip = a ? chipOf(a.machine, a.ended) : null;
  const label = `Session ${session.name}, ${a ? a.persona_name || a.persona : "plain shell"}, ${said}${chip ? `, ${chip.said}` : ""}`;
  const attrs = { class: `sesschip ${state}`, "data-waits": waits ? "" : undefined, "aria-label": label, title: label };
  const body = html`<${PersonaBadge} persona=${personaOf(a)} hidden /><span class="name">${session.name}</span><span class="word">${word}</span>${a && html`<${StateChip} machine=${a.machine} ended=${a.ended} short />`}`;
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

// Recents and pins, per viewer, in this browser only. A blocked storage just means none.
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

// --- the personas' GitHub Apps (012 FR-032) ----------------------------------------------------------------------------
// hubd writes the manifest and keeps the nonce, the code exchange and the key; this page posts the manifest form to GitHub
// from your browser, as GitHub's manifest flow wants, and hands GitHub's code back to hubd.
const PERMISSION_WORDS = { contents: "Contents", metadata: "Metadata", issues: "Issues", pull_requests: "Pull requests", actions: "Actions",
  administration: "Administration", organization_projects: "Organization projects" };
function permissionWords(permissions) {
  return Object.entries(permissions || {}).map(([name, level]) => `${PERMISSION_WORDS[name] || name}: ${level}`).join(" · ");
}
function appState(row) {
  if (!row.app) return "No App yet: its writes go out as you";
  if (row.installed === true) return `Has an App, ${row.slug}, installed in the organization`;
  return `Has an App, ${row.slug}; whether it's installed isn't checked here`;
}

// GitHub's manifest flow: a plain form post, from this page, to the URL hubd gave, never anywhere but github.com.
function submitManifest(url, manifest) {
  if (!String(url).startsWith("https://github.com/")) throw new Error("the manifest doesn't go to GitHub");
  const form = document.createElement("form");
  form.method = "post";
  form.action = url;
  const field = document.createElement("input");
  field.type = "hidden";
  field.name = "manifest";
  field.value = JSON.stringify(manifest);
  form.append(field);
  document.body.append(form);
  form.submit();
}

const convertedStates = new Set(); // a state goes to hubd once, even if the page draws again
function AppsPage({ query }) {
  const list = useLoad(() => api("apps"), []);
  const [made, setMade] = useState(null);
  const [replacing, setReplacing] = useState(null);
  const finish = useAct(() => list.reload());
  const create = useAct();
  useEffect(() => {
    const { code, state } = query;
    if (!code && !state) return;
    history.replaceState(null, "", hash("apps")); // the code works once, but it shouldn't stay in the address or the history
    if (!code || !state || convertedStates.has(state)) return;
    convertedStates.add(state);
    finish.run(async () => setMade(await post("apps/convert", { code, state })));
  }, []);
  const start = (persona, replace) => create.run(async () => {
    const reply = await post("apps/manifest", { persona, replace });
    submitManifest(reply.url, reply.manifest);
  });
  const rows = list.data ? list.data.apps.filter((r) => r.persona) : [];
  const tableError = list.data && list.data.apps.find((r) => r.error);
  return html`<main class="page"><div class="stack tight"><${Eyebrow} soft>Settings<//><h1>GitHub Apps</h1></div>
    <p class="small soft">Each persona posts on GitHub as its own App, so its work shows it came from an agent. Creating one opens GitHub's form with the App already described: you press Create there, and GitHub sends you back here. Its private key stays with hubd on this computer.</p>
    ${query.failed && html`<div class="notice" role="status"><span>GitHub's answer didn't carry a code and a state, so nothing was created here. Start again below.</span></div>`}
    ${finish.busy && html`<div class="notice quiet" role="status"><span>Finishing the App with GitHub…</span></div>`}
    <${Err} text=${finish.error} />
    ${made && html`<div class="notice" role="status"><span class="grow"><b>Created ${made.slug}</b> for ${made.persona}${made.replaced ? ", in place of its earlier App" : ""}. Next, install it on the organization: GitHub asks whether it gets all repositories or the ones you choose.</span>
      <a class="button primary" href=${made.install_url} target="_blank" rel="noopener noreferrer">Install on the organization</a></div>`}
    <${Err} text=${list.error || (tableError && tableError.error)} />
    <${Err} text=${create.error} />
    ${!list.data && !list.error && html`<p class="soft">Loading…</p>`}
    <section class="stack tight" aria-label="Personas">
      ${rows.map((r) => html`<div class="app-row" key=${r.persona}>
        <span class="stack tight app-row-text"><span><b>${r.name}</b> <span class="mono small soft">${r.persona}</span></span>
          <span class="small">${appState(r)}</span>
          <span class="small soft">Asks GitHub for ${permissionWords(r.permissions)}</span></span>
        <span class="row" style="gap: 8px">
          ${!r.app && html`<button disabled=${create.busy} onClick=${() => start(r.persona, false)}>Create the App on GitHub</button>`}
          ${r.app && r.install_url && html`<a class="button" href=${r.install_url} target="_blank" rel="noopener noreferrer">Install or change repositories</a>`}
          ${r.app && replacing !== r.persona && html`<button class="plain" onClick=${() => setReplacing(r.persona)}>Replace…</button>`}</span>
        ${replacing === r.persona && html`<div class="notice quiet" style="flex-basis: 100%"><span class="grow">A new App takes over from ${r.slug} once GitHub creates it. The old one stays on GitHub until you delete it there, and its name is taken: change the name on GitHub's form.</span>
          <button class="primary" disabled=${create.busy} onClick=${() => start(r.persona, true)}>Create a new App on GitHub</button>
          <button onClick=${() => setReplacing(null)}>Cancel</button></div>`}</div>`)}
    </section></main>`;
}

function GitHubAppsCard() {
  const { data } = useLoad(() => api("apps").catch(() => null), [], 300000);
  if (!data) return null;
  const rows = data.apps.filter((r) => r.persona);
  const have = rows.filter((r) => r.app).length;
  return html`<section aria-labelledby="h-apps" class="stack tight">
    <h2 id="h-apps" class="dotted" style="font-size: 21px; font-weight: 600">GitHub Apps</h2>
    <span class="small">${have} of ${count(rows.length, "persona")} ${have === 1 ? "has its" : "have their"} own App${have < rows.length ? "; the rest post as you" : ""}.</span>
    <a class="small" href=${hash("apps")}>Create or install Apps</a></section>`;
}

// 007 FR-001: what waits for you, from the interactions' counts: how many, of which kinds, and the longest wait. It opens Needs you.
const KIND_PLURAL = { permission: "permissions", question: "questions", decision: "decisions", suggestion: "suggestions", result: "results" };
const waitWords = (s) => (s < 90 ? "under a minute" : s < 5400 ? `${Math.round(s / 60)} min` : s < 129600 ? `${Math.round(s / 3600)} h` : `${Math.round(s / 86400)} d`);
function NeedsYouCard({ asks }) {
  const c = asks.interactions.counts;
  const kinds = Object.entries(c.by_kind || {}).filter(([, n]) => n > 0).map(([k, n]) => `${n} ${n === 1 ? k : KIND_PLURAL[k] || k}`);
  return html`<button type="button" class="stat needs-card ${c.blocking ? "blocking" : ""}" onClick=${() => needsYou()} aria-label=${needsLabel(asks)}>
    <${Eyebrow} soft>Needs you<//><b>${c.pending || "Nothing"}</b>
    <span class="small">${c.pending ? kinds.join(" · ") : "nothing waiting"}${c.blocking ? ` · ${c.blocking} blocking a session` : ""}</span>
    <span class="small soft">${c.pending ? `longest wait ${waitWords(c.longest_wait)}` : asks.stale ? "hubd can't be reached" : " "}</span></button>`;
}

// The repositories a session works in: what it covers, else its own.
const sessionRepos = (s) => {
  const a = s.agent || {};
  return new Set([...(a.covers || []).map((c) => c.repo), ...(a.repo ? [a.repo] : [])]);
};

// 007 FR-004: failing runs, waiting sessions, open pull requests, then the latest activity, as github.attention_key.
function byAttention(a, b) {
  const x = a.attention, y = b.attention;
  return (y.failing_runs - x.failing_runs) || (b.waiting - a.waiting) || (y.open_prs - x.open_prs)
    || String(y.last_activity || "").localeCompare(String(x.last_activity || ""));
}
const needsAttention = (r) => r.attention.failing_runs > 0 || r.waiting > 0;
const LAYER_SHOWN = 5; // 007 FR-005: then "Show N more"
// 007 FR-004–FR-006: a layer's repositories that fit the filter, in attention order; the first LAYER_SHOWN of them unless
// all are asked for or a filter is typed; and how many more there are.
function layerRows(rows, { needle = "", attentionOnly = false, all = false } = {}) {
  const fits = rows.filter((r) => (!needle || `${r.name} ${r.description || ""}`.toLowerCase().includes(needle)) && (!attentionOnly || needsAttention(r)));
  const sorted = [...fits].sort(byAttention);
  const shown = all || needle ? sorted : sorted.slice(0, LAYER_SHOWN);
  return { rows: sorted, shown, more: sorted.length - shown.length };
}

// 007 FR-007: one repository, as a row of its layer. The name opens its details beside the list.
function RepoCard({ r, marks, picked, onPick }) {
  const kind = r.attention.failing_runs > 0 ? "fail" : CI_KIND[r.ci] || "open";
  const shown = r.sessions.slice(0, MAX_ROW_CHIPS);
  return html`<div class="repo keycap" data-picked=${picked ? "" : undefined}>
    <button type="button" class="title plain" aria-pressed=${picked ? "true" : "false"} onClick=${onPick}>
      <${StateIcon} kind=${kind} label=${r.attention.failing_runs > 0 ? `${count(r.attention.failing_runs, "workflow")} failing` : CI_WORD[kind]} /><span class="grow">${r.name}</span></button>
    <span class="mono" style="font-size: 12.5px">${count(r.issues, "issue")} · ${r.prs} PR${r.prs === 1 ? "" : "s"}${r.failing_prs ? ` (${r.failing_prs} failing)` : ""}</span>
    <${Strip} marks=${marks} />
    <span class="small" style="overflow-wrap: anywhere">${r.last_commit ? html`<span class="soft">Last commit</span> ${r.last_commit.title || r.last_commit.oid.slice(0, 7)}` : html`<span class="soft">No commits</span>`}</span>
    <span class="soft" style="font-size: 12.5px">${r.last_activity ? `active ${ago(r.last_activity)}` : "no activity"} · ${r.release || "no release"}</span>
    <span class="row" style="gap: 6px; width: 100%">${shown.map((s) => html`<${SessionChip} key=${s.name} session=${s} href=${hash("shells", { name: s.name })} />`)}
      ${r.sessions.length > shown.length && html`<a class="small" href=${hash("shells")}>${r.sessions.length - shown.length} more</a>`}
      <span class="grow"></span>
      <button type="button" class="pen" onClick=${() => launch({ repos: [r.name], from: { view: "Overview" } })}><${TermIcon} />Launch…</button></span>
  </div>`;
}

function KnowledgeStat() {
  const { data, error } = useLoad(() => api("docs/status"), [], 120000);
  return html`<a class="stat" href=${hash("knowledge")}><${Eyebrow} soft>Knowledge<//>
    <b>${error ? "unknown" : data ? (data.chunks == null ? data.state : data.chunks.toLocaleString()) : "…"}</b>
    <span class="small soft">${data ? `passages indexed · index ${data.state}` : error || " "}</span></a>`;
}

// The host login's GitHub API budget, as one of Overview's stats.
function BudgetStat() {
  const { data, error } = useLoad(() => api("limits"), [], 120000);
  const pct = data && data.limit ? Math.round(data.remaining / data.limit * 100) : 0;
  const reset = data ? new Date(data.reset * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
  return html`<div class="stat"><${Eyebrow} soft>GitHub API<//><b>${data ? `${pct}%` : error ? "unknown" : "…"}</b>
    ${data && html`<span class="bar ink" style="width: 100%; height: 8px" aria-hidden="true"><i style="width: ${pct}%"></i></span>`}
    <span class="small soft">${data ? `${data.remaining.toLocaleString()} of ${data.limit.toLocaleString()} left · resets ${reset}` : error || " "}</span></div>`;
}

function Overview({ asks }) {
  const { data, error } = useLoad(() => api("overview"), [], 60000);
  const strips = useLoad(() => api("overview/runs"), [], 300000);
  const sessions = useSessions();
  const [picked, setPicked] = useState(null);
  const [filter, setFilter] = useState("");
  const [attentionOnly, setAttentionOnly] = useState(false);
  const [collapsed, setCollapsed] = useState(() => new Set());
  const [opened, setOpened] = useState(() => new Set()); // layers showing all their repositories
  const list = sessions.data || [];
  if (!data) return html`<main class="page"><h1>Overview</h1><${Err} text=${error} />${!error && html`<p class="soft">Loading…</p>`}</main>`;
  const withSessions = (r) => {
    const on = list.filter((s) => sessionRepos(s).has(r.name));
    return { ...r, sessions: on, waiting: on.filter((s) => s.agent && s.agent.waiting).length };
  };
  const placed = data.groups.filter((g) => g.key !== "unplaced");
  const unplaced = data.groups.find((g) => g.key === "unplaced");
  const every = data.groups.flatMap((g) => g.repos.map((r) => ({ ...withSessions(r), layer: g.title })));
  const current = every.find((r) => r.name === picked) || [...every].sort(byAttention)[0];
  const needle = filter.trim().toLowerCase();
  const layers = placed.map((g) => ({ ...g, ...layerRows(g.repos.map(withSessions), { needle, attentionOnly, all: opened.has(g.key) }) }));
  const running = list.filter((s) => s.agent && !s.agent.ended).length;
  const waiting = list.filter((s) => s.agent && s.agent.waiting).length;
  const toggle = (set, key) => { const x = new Set(set); if (!x.delete(key)) x.add(key); return x; };
  const shownUnplaced = unplaced ? layerRows(unplaced.repos.map(withSessions), { needle, attentionOnly, all: true }).rows : [];
  return html`<main class="page">
    <div class="row" style="justify-content: space-between; align-items: flex-end; gap: 12px 24px">
      <div class="stack tight"><${Eyebrow} soft>GlassineOS org · ${data.totals.repos} repositories · ${placed.length} layers<//><h1>Overview</h1></div>
</div>
    <${Err} text=${error} />
    <section class="stats" aria-label="Org totals">
      <${NeedsYouCard} asks=${asks} />
      <a class="stat" href=${hash("shells")}><${Eyebrow} soft>Running sessions<//><b>${running}</b><span class="small soft">${waiting ? `${waiting} waiting for you` : "none waiting"}</span></a>
      <a class="stat" href=${hash("work", { tab: "issues" })}><${Eyebrow} soft>Open issues<//><b>${data.totals.issues}</b><span class="small soft">across ${data.totals.repos} repositories</span></a>
      <a class="stat" href=${hash("work", { tab: "prs" })}><${Eyebrow} soft>Open PRs<//><b>${data.totals.prs}</b><span class="small soft">${data.totals.failing_prs == null ? "checks not counted until the first sync" : data.totals.failing_prs ? `${data.totals.failing_prs} failing` : "none failing"}</span></a>
      <${KnowledgeStat} />
      <${BudgetStat} />
    </section>
    <div class="columns">
      <section class="wide stack" style="gap: 24px" aria-labelledby="h-layers">
        <div class="row dotted"><h2 id="h-layers" class="grow" style="font-size: 27px; line-height: 1.2; font-weight: 600">Repositories by layer</h2>
          <span class="small soft">Layers from <code>config/repos.toml</code>, each sorted by what needs attention</span></div>
        <div class="filters">
          <form class="searchbox" role="search" onSubmit=${(e) => e.preventDefault()}><${SearchIcon} /><label class="sr" for="ov-filter">Filter repositories</label>
            <input id="ov-filter" type="search" placeholder="Filter by name or description" value=${filter} onInput=${(e) => setFilter(e.target.value)} /></form>
          <label class="row small" style="gap: 8px"><input type="checkbox" role="switch" style="min-height: 0" checked=${attentionOnly} onChange=${(e) => setAttentionOnly(e.target.checked)} /> Needs attention only</label>
          <button class="plain" onClick=${() => setCollapsed(new Set(placed.map((g) => g.key)))}>Collapse all</button>
          <button class="plain" onClick=${() => setCollapsed(new Set())}>Expand all</button>
        </div>
        ${layers.map((g, i) => {
          const shut = collapsed.has(g.key);
          const failing = g.rows.filter((r) => r.attention.failing_runs > 0).length;
          return html`<div class="layer" key=${g.key}>
          <div class="name" title=${g.summary}><span class="num" aria-hidden="true">${i + 1}</span>
            <h3><button type="button" class="plain layer-toggle" aria-expanded=${shut ? "false" : "true"} onClick=${() => setCollapsed(toggle(collapsed, g.key))}>${shut ? "▸" : "▾"} ${g.title}</button></h3>
            ${shut && html`<span class="small soft">${g.rows.length} ${g.rows.length === 1 ? "repository" : "repositories"}${failing ? `, ${failing} failing` : ""}</span>`}</div>
          ${!shut && html`<div class="repos">${g.shown.map((r) => html`<${RepoCard} key=${r.name} r=${r} marks=${strips.data ? strips.data[r.name] : null}
              picked=${current && current.name === r.name} onPick=${() => setPicked(r.name)} />`)}
            ${!g.rows.length && html`<span class="small soft">${attentionOnly ? "Nothing here needs attention." : "No repository matches."}</span>`}
            ${g.more > 0 && html`<button type="button" class="plain" onClick=${() => setOpened(toggle(opened, g.key))}>Show ${g.more} more</button>`}
            ${!needle && opened.has(g.key) && g.rows.length > LAYER_SHOWN && html`<button type="button" class="plain" onClick=${() => setOpened(toggle(opened, g.key))}>Show fewer</button>`}</div>`}
        </div>`;
        })}
        ${unplaced && html`<div class="unplaced"><span class="eyebrow" style="flex: 0 0 170px">Unplaced · ${unplaced.repos.length}</span>
          <span class="mono" style="font-weight: 600">${(needle || attentionOnly ? shownUnplaced : unplaced.repos).map((r) => r.name).join(", ") || "none match"}</span>
          <span class="small soft" style="flex: 1 1 240px">In the org but not in <code>config/repos.toml</code>. Add to a layer there.</span></div>`}
        <p class="small soft">Run strip: last 10 workflow runs on the default branch, oldest first. Outlined: passed · filled: failed · dashed: running. A repository's failing count is its workflows whose newest run there failed.</p>
      </section>
      <aside class="aside stack" style="gap: 24px">
        ${current && html`<${RepoDetail} key=${current.name} repo=${current} layer=${current.layer} />`}
        <${DeviceCard} asks=${asks} />
        <${Workspace} />
        <${RepoCopies} />
        <${GitHubAppsCard} />
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

// 007 FR-011: "Plan issues…" opens Launch with the road action, on the roadmap item.
// The item is already on the board: the notes say to plan its sub-issues under it, not a new strategic issue. The person reads and can edit them.
const planIssues = (repo, number, view) => launch({ action: "new-roadmap-item", repos: [repo], context: `${repo}#${number}`,
  notes: `Plan the sub-issues of ${repo}#${number}, which is already on the roadmap. Draft no strategic issue: every draft's parent is ${repo}#${number}.`,
  pins: [{ kind: "ref", label: `${repo}#${number}` }], from: { view, ref: `${repo}#${number}` } });

// 007 FR-010: progress per repository, a bar each with the counts in words.
function Progress({ rows }) {
  if (!rows.length) return html`<p class="small soft">No issues are part of it yet.</p>`;
  return html`<ul class="stack tight progress">${rows.map((p) => {
    const pct = p.total ? Math.round(p.done / p.total * 100) : 0;
    const words = `${p.done} of ${p.total} done`;
    return html`<li class="row" style="flex-wrap: nowrap; gap: 8px"><span class="mono" style="flex: 0 0 auto; font-size: 12.5px">${p.repo}</span>
      <span class="bar grow" role="progressbar" aria-label=${`${p.repo}: ${words}`} aria-valuenow=${pct} aria-valuemin="0" aria-valuemax="100" style="height: 8px"><i style="width: ${pct}%"></i></span>
      <span class="small" style="flex: 0 0 auto">${words}</span></li>`;
  })}</ul>`;
}

function RoadmapCard({ item, sessions, left, right, busy, onMove, url }) {
  const ref = item.repo ? `${item.repo}#${item.number}` : null;
  const kind = item.kind === "PullRequest" ? "pr" : "issue";
  const open = item.repo ? hash("work", { tab: kind === "pr" ? "prs" : "issues", repo: item.repo, item: item.number, ...(kind === "issue" ? { road: 1 } : {}) }) : url;
  const on = item.repo ? sessionsOn({ kind, repo: item.repo, number: item.number }, sessions) : [];
  const targets = item.progress.map((p) => p.repo).filter((r) => r !== item.repo);
  return html`<article class="card keycap">
    <div class="row" style="justify-content: space-between; align-items: baseline; gap: 4px 8px">
      ${ref && html`<span class="ref">${ref}</span>`}
      <span class="small soft">${targets.length ? `→ ${targets.join(", ")}` : item.repo ? `→ ${item.repo}` : "draft"}</span></div>
    <a class="title" href=${open}>${item.title}</a>
    ${item.note && html`<p class="small soft">${item.note}</p>`}
    ${kind === "issue" && item.repo && html`<${Progress} rows=${item.progress} />`}
    <div class="small"><span class="soft">Who: </span>${item.assignees.join(", ") || "nobody assigned"}</div>
    ${on.length > 0 && html`<div class="row" style="gap: 6px">${on.slice(0, MAX_ROW_CHIPS).map((s) => html`<${SessionChip} key=${s.name} session=${s} />`)}
      ${on.length > MAX_ROW_CHIPS && html`<a class="small" href=${hash("shells")}>${on.length - MAX_ROW_CHIPS} more</a>`}</div>`}
    <div class="row" style="flex-wrap: nowrap; gap: 6px">
      ${kind === "issue" && item.repo && html`<button type="button" class="pen grow" onClick=${() => planIssues(item.repo, item.number, "Roadmap")}><${TermIcon} />Plan issues…</button>`}
      <span class=${kind === "issue" && item.repo ? "" : "grow"}></span>
      <button class="icon" aria-label="Move left${left ? ` to ${left.name}` : ""}" disabled=${busy || !left} onClick=${() => onMove(left)}><${Chevron} /></button>
      <button class="icon" aria-label="Move right${right ? ` to ${right.name}` : ""}" disabled=${busy || !right} onClick=${() => onMove(right)}><${Chevron} right /></button>
    </div></article>`;
}

function Roadmap() {
  const { data, error, reload } = useLoad(() => api("project"), [], 120000);
  const hubIssues = useLoad(() => api("issues?repo=hub"), []);
  const sessions = useSessions();
  const [adding, setAdding] = useState(false);
  const act = useAct(async () => { await reload(); await hubIssues.reload(); });
  const title = html`<div class="stack tight" style="max-width: 68ch"><${Eyebrow} soft>Org project · ${data && data.title ? data.title : "GlassineOS roadmap"}<//>
    <h1>Roadmap</h1>
    <p class="soft" style="font-size: 17px; line-height: 1.65">Strategic issues live in GlassineOS/hub. A card's progress counts its sub-issues and the issues that say they're "Part of" it, per repository.</p></div>`;
  if (data && data.needs_scope) {
    return html`<main class="page close">${title}<div class="notice"><span>The host's GitHub login can't see Projects yet. Run this on the host, then reload:</span><pre class="mono">${data.command}</pre></div></main>`;
  }
  if (data && data.missing) {
    return html`<main class="page close">${title}<div class="notice"><span>The organization has no open project called “${data.title}”. Create it once on the host:</span><pre class="mono">gh project create --owner GlassineOS --title "${data.title}"</pre></div></main>`;
  }
  const onBoard = new Set(data ? data.columns.flatMap((c) => c.items.filter((i) => i.repo === "hub").map((i) => i.number)) : []);
  const orphans = data && hubIssues.data ? hubIssues.data.filter((i) => !onBoard.has(i.number)) : [];
  // A move sets the Status to the first mapped option of the nearest column that way which has one (a column with none is
  // skipped): an option the map doesn't name would land the card back under Planned.
  const target = (index, step) => {
    for (let i = index + step; i >= 0 && i < data.columns.length; i += step) {
      const option = data.columns[i].options.find((o) => o.mapped);
      if (option) return { name: data.columns[i].name, option: option.id };
    }
    return null;
  };
  const move = (item, to) => act.run(() => post("project/move", { project: data.id, item: item.id, field: data.status_field, option: to.option }));
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
    ${data && data.unmapped && data.unmapped.length > 0 && html`<p class="small soft">Status ${data.unmapped.length === 1 ? "option" : "options"} with no column, shown under Planned: ${data.unmapped.join(", ")}. The map is <code>[roadmap]</code> in <code>config/repos.toml</code>.</p>`}
    ${!data && !error && html`<p class="soft">Loading…</p>`}
    ${data && html`<div class="board">${data.columns.map((col, index) => html`<section class="column" aria-label=${col.name}>
        <header class="dotted"><h2 class="eyebrow">${col.name}</h2><span class="mono" style="font-size: 13px; font-weight: 600">${col.items.length}</span></header>
        ${col.items.map((item) => html`<${RoadmapCard} key=${item.id} item=${item} sessions=${sessions.data} url=${data.url} busy=${act.busy}
          left=${target(index, -1)} right=${target(index, 1)} onMove=${(to) => move(item, to)} />`)}
        ${!col.items.length && html`<p class="small soft">Nothing here.</p>`}</section>`)}</div>
    <p class="small soft">Arrows move a card one column, past any column no Status option maps to. Progress counts an issue once, closed as done${data.from_store ? "" : "; without the work store only sub-issues count"}.</p>`}
  </main>`;
}

// --- Launch: notes and pins for the planner ------------------------------------------------
const STEER_CHIPS = {
  pr: ["error paths first", "keep the diff small", "check it against the docs", "add tests"],
  issue: ["only propose, don't apply", "look for duplicates", "keep the change small"],
  run: ["compare with earlier runs", "don't touch the runner image"],
};
const PIN_WORDS = { thread: "Review thread", ref: "Issue / PR", file: "Repo file", docs: "Docs page", url: "Link", text: "Text snippet", report: "Kept report" };
const PIN_HINTS = { ref: "hub#44", file: "kernel:drivers/gpu/drm/epd/epd_lut.c", docs: "docs path", text: "Something the agent should know" };
const pinKind = (v) => (/^https?:/.test(v) ? "url" : /#\d/.test(v) ? "ref" : v.indexOf(":") > 0 ? "file" : "docs");

function SteerFields({ kind, notes, pins, onNotes, onPins, rows }) {
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
      <textarea rows=${rows || 2} maxlength="4000" placeholder="What matters most here" value=${notes} onInput=${(e) => onNotes(e.target.value)}></textarea></label>
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

// 006 FR-007: the one action that fits the item best. Fix if failing (a run without a fix action: investigate), address if a
// review asked for changes, triage if nobody has labelled it, else review a PR, implement an issue, investigate a run.
// Work's rows use it too.
const BEST_VERB = { pr: "review", issue: "implement", run: "investigate" };
function bestAction(kind, facts, offered) {
  const verbs = facts.failing ? ["fix", "investigate"]
    : kind === "pr" && (facts.changesRequested || facts.openThreads > 0) ? ["address"]
    : kind === "issue" && facts.untriaged ? ["triage"] : [BEST_VERB[kind]];
  for (const verb of verbs) {
    const found = offered.find((a) => a.verb === verb);
    if (found) return found;
  }
  return offered.find((a) => a.verb) || offered[0] || null;
}

const useKindActions = (kind) => useLoad(() => api(`agents/actions${params({ object: kind })}`), [kind]);

// 006 FR-015: the kind's agent actions as blue buttons, the best one filled, and "New work from this…". Each opens Launch on the item.
function LaunchRow({ kind, repo, number, facts, road }) {
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
      ${road && html`<button class="pen" onClick=${() => planIssues(repo, number, "Work")}><${TermIcon} />Plan issues…</button>`}
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
function SessionsOn({ kind, repo, number, facts, sessions, phaseOf, place, setPhase, asks, onReload, onEnded }) {
  const here = `${repo}#${number}`;
  const embedded = sessions.filter((s) => phaseOf(s) === "embedded");
  const behind = sessions.filter((s) => phaseOf(s) !== "embedded");
  const [tab, setTab] = useState(null);
  const current = embedded.find((s) => s.name === tab) || embedded[0];
  return html`<section class="stack" aria-labelledby="h-sessions-on" style="gap: 10px">
    <h2 id="h-sessions-on" style="font-size: 19px; font-weight: 600">Sessions on ${here} · ${sessions.length}</h2>
    ${!sessions.length && html`<${SuggestBest} kind=${kind} repo=${repo} number=${number} facts=${facts} />`}
    ${embedded.length > 0 && html`<div role="tablist" aria-label="Sessions on ${here}" class="tabs">${embedded.map((s) => html`<button role="tab" aria-selected=${s === current ? "true" : "false"} onClick=${() => setTab(s.name)}>
        <${PersonaBadge} persona=${personaOf(s.agent)} hidden /> ${s.agent.persona_name || s.agent.persona} <span class="mono soft" style="font-size: 12.5px">${s.name}</span> <${StateChip} machine=${s.agent.machine} ended=${s.agent.ended} /></button>`)}</div>
      <${SessionView} key=${current.name} session=${current} mode="embedded" asks=${asks} here=${here}
        onView=${(m) => setPhase(current.name, m)} onEnded=${onEnded || onReload} onGone=${onReload} />`}
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
  useModal(ref);
  const names = [...new Set([...(all.data || []).map((l) => l.name), ...have])].sort((a, b) => a.localeCompare(b));
  const add = names.filter((n) => on.has(n) && !have.includes(n));
  const remove = have.filter((n) => !on.has(n));
  const apply = () => act.run(async () => { await post(path, { add, remove }); onDone(`Labels changed${add.length ? `: +${add.join(", +")}` : ""}${remove.length ? `${add.length ? "," : ":"} −${remove.join(", −")}` : ""}`); });
  return html`<dialog ref=${ref} aria-labelledby="labels-h" onClose=${onNo}><h2 id="labels-h">Labels</h2>
    <${Err} text=${all.error || act.error} />${!all.data && !all.error && html`<p class="soft">Loading…</p>`}
    <div class="stack" style="gap: 4px; max-height: 50vh; overflow: auto">${names.map((n) => html`<label class="row" style="gap: 8px"><input type="checkbox" checked=${on.has(n)}
      onChange=${() => setOn((s) => { const x = new Set(s); if (!x.delete(n)) x.add(n); return x; })} />${n}</label>`)}</div>
    <div class="row"><button class="gh" disabled=${act.busy || !(add.length || remove.length)} onClick=${apply}>Apply</button><button onClick=${onNo}>Cancel</button></div></dialog>`;
}

function MergeDialog({ data, onYes, onNo }) {
  const ref = useRef();
  const [method, setMethod] = useState("squash");
  useModal(ref);
  return html`<dialog ref=${ref} aria-labelledby="merge-h" onClose=${onNo}><h2 id="merge-h">Merge this pull request?</h2>
    <p>${data.repo}#${data.number} at <span class="mono">${(data.headRefOid || "").slice(0, 12)}</span> into ${data.baseRefName}. Checks: ${data.checks}. If it has moved on from that commit, the merge fails.</p>
    <label class="field"><span>How</span><select value=${method} onChange=${(e) => setMethod(e.target.value)}>
      <option value="squash">Squash and merge</option><option value="merge">Merge commit</option><option value="rebase">Rebase and merge</option></select></label>
    <div class="row"><button class="gh" onClick=${() => onYes(method)}>Merge</button><button onClick=${onNo}>Cancel</button></div></dialog>`;
}

// Everything the black button offers for one kind (006 FR-030, FR-032, FR-033). Each entry says why it's off, or null.
function ghEntries({ kind, data, repo, number, base, behind }) {
  const page = { label: "Open on GitHub", disabled: null, href: data.url };
  if (kind === "work") { // 006 FR-034: each opens its form; the form does the call. Run workflow… first on the Runs tab.
    const made = [{ id: "new-issue", label: "New issue…", panel: "new", disabled: null }, { id: "dispatch", label: "Run workflow…", panel: "dispatch", disabled: null }];
    return [...(data.tab === "actions" ? made.reverse() : made), page];
  }
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
    const close = (reason, label) => ({ id: `close-${reason}`, label, done: `Closed as ${reason}`, run: () => post(`${base}/close`, { reason }),
      disabled: open ? null : "already closed", confirm: { title: `${label}?`, text: `${repo}#${number}: ${data.title}`, label } });
    return [
      close("completed", "Close as completed"),
      close("not planned", "Close as not planned"),
      { id: "reopen", label: "Reopen", done: "Reopened", run: () => post(`${base}/reopen`), disabled: open ? "it's open" : null },
      { id: "labels", label: "Labels…", labels: `${base}/labels`, disabled: null },
      { id: "assign", label: "Assign to me", done: "Assigned", run: () => post(`${base}/assign-me`), disabled: null },
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
function GhActions({ kind, data, repo, number, base, behind, onDone, onPanel }) {
  const entries = ghEntries({ kind, data, repo, number, base, behind });
  const main = entries.find((e) => !e.disabled && !e.href) || entries.find((e) => !e.href) || entries[0];
  const [menu, setMenu] = useState(false);
  const [modal, setModal] = useState(null);
  const [said, setSaid] = useState("");
  const [confirm, dialog] = useConfirm();
  const act = useAct();
  const box = useRef();
  const arrow = useRef();
  const shut = () => { setMenu(false); if (arrow.current) arrow.current.focus(); };
  // 001 FR-016: the menu opens with focus on its first item; arrows move, Esc closes it back onto its button.
  useEffect(() => {
    if (!menu) return undefined;
    const first = box.current && box.current.querySelector('.ghmenu [role="menuitem"]');
    if (first) first.focus();
    const away = (e) => { if (box.current && !box.current.contains(e.target)) setMenu(false); };
    const esc = (e) => { if (e.key === "Escape") { e.preventDefault(); shut(); } };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("pointerdown", away); document.removeEventListener("keydown", esc); };
  }, [menu]);
  // A dialog it opened has closed: focus comes back to the GitHub actions button, not the page.
  const hadModal = useRef(null);
  useEffect(() => {
    if (hadModal.current && !modal && focusLost() && arrow.current) arrow.current.focus();
    hadModal.current = modal;
  }, [modal]);
  const menuKeys = (e) => {
    const items = [...e.currentTarget.querySelectorAll('[role="menuitem"]')];
    const at = items.indexOf(document.activeElement);
    const to = { ArrowDown: at + 1, ArrowUp: at - 1, Home: 0, End: items.length - 1 }[e.key];
    if (to === undefined || !items.length) { if (e.key === "Tab") setMenu(false); return; }
    e.preventDefault();
    items[(to + items.length) % items.length].focus();
  };
  // The view reloads at once and again after a few seconds, as GitHub can take a moment to show the change (FR-038).
  const finish = async (words) => { setSaid(`${words}.`); await onDone(); setTimeout(onDone, 4000); };
  const go = (e) => {
    if (e.disabled) return;
    if (menu) shut();
    if (e.href) { window.open(e.href, "_blank", "noopener,noreferrer"); return; }
    if (e.panel) { onPanel(e.panel); return; }
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
      <button ref=${arrow} class="gh arrow" aria-haspopup="menu" aria-expanded=${menu ? "true" : "false"} aria-label="More actions on GitHub" disabled=${act.busy} onClick=${() => setMenu(!menu)}>
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M3 5l4 4 4-4" /></svg></button></div>
    <span class="small soft">On GitHub, as <span class="mono">${HOST_USER || "the host's gh"}</span></span>
    ${menu && html`<ul role="menu" class="ghmenu" aria-label="Actions on GitHub" onKeyDown=${menuKeys}>${entries.map((e) => html`<li role="none">
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
  useModal(ref);
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

// Whether a review note belongs under this row: a note on the old side (LEFT) counts old-file lines, so it matches a row's `a`
// (a removed line, or an unchanged one); any other note counts new-file lines and matches `b`.
function noteBelongsTo(thread, row) {
  if (!thread.line) return false;
  if (thread.side === "LEFT") return row.kind !== "add" && row.a === thread.line;
  return row.kind !== "del" && row.b === thread.line;
}

// One file in Files changed (006 FR-020, FR-021): opens to its hunks with line numbers and the review notes at their lines.
// A large file waits for "load the diff".
function FileDiff({ base, file, threads }) {
  const [open, setOpen] = useState(false);
  const [asked, setAsked] = useState(!file.large);
  const diff = useLoad(() => (open && asked ? api(`${base}/diff${params({ path: file.path })}`) : Promise.resolve(null)), [open, asked, file.path]);
  const notes = threads.filter((t) => t.path === file.path);
  const at = (row) => notes.filter((t) => noteBelongsTo(t, row));
  const loose = notes.filter((t) => !t.line);
  const rows = diff.data ? diffRows(diff.data) : [];
  return html`<div class="filediff">
    <button class="fileline" aria-expanded=${open ? "true" : "false"} onClick=${() => setOpen(!open)}>
      <${Chevron} right=${!open} /><span class="mono grow" style="overflow-wrap: anywhere">${file.path}</span>
      ${notes.length > 0 && html`<span class="badge dim">${count(notes.length, "note")}</span>`}
      <span class="mono small"><span class="add">+${file.additions}</span> <span class="del">−${file.deletions}</span></span></button>
    ${open && !asked && html`<div class="row" style="padding: 8px 12px"><span class="small soft grow">${file.additions + file.deletions} lines changed.</span>
      <button onClick=${() => setAsked(true)}>Large file — load the diff</button></div>`}
    ${open && asked && html`<${Err} text=${diff.error} />${!diff.data && !diff.error && html`<p class="small soft" style="padding: 8px 12px">Loading…</p>`}
      ${loose.length > 0 && html`<div class="diffnotes">${loose.map((t) => html`<${DiffNote} thread=${t} />`)}</div>`}
      ${typeof diff.data === "string" && rows.length === 0 && html`<p class="small soft" style="padding: 8px 12px">No lines to show: a rename, a mode change, an empty file or a binary one.</p>`}
      ${rows.length > 0 && html`<div class="diffbox"><table class="diff"><tbody>${rows.map((r) => html`
        <tr class=${r.kind}><td class="ln">${r.a || ""}</td><td class="ln">${r.b || ""}</td><td class="code">${r.kind === "add" ? "+" : r.kind === "del" ? "−" : " "}${r.text}</td></tr>
        ${at(r).length > 0 && html`<tr class="notes"><td colspan="3">${at(r).map((t) => html`<${DiffNote} thread=${t} />`)}</td></tr>`}`)}</tbody></table></div>`}`}
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
      ${d.lines.length ? html`<ol class="steplog" data-theme="white-night" aria-label="Log of the failed step">${d.lines.map((l) => html`<li class=${l.error ? "err" : ""} value=${l.n}>${l.error && html`<span class="sr">error: </span>`}${l.text}</li>`)}</ol>`
        : html`<p class="small soft">GitHub kept no log for this step.</p>`}`
      : html`<p class="soft">No job failed in this run.</p>`}
    <${Err} text=${logs.error} />
    <div class="row">${d.log_url && html`<a href=${d.log_url} target="_blank" rel="noreferrer noopener">The job on GitHub</a>`}
      <button class="plain" disabled=${logs.busy} onClick=${() => logs.run(async () => setFull(full === null ? await api(`runs/${repo}/${id}/log?all=1`) : null))}>${full === null ? "Full log here" : "Hide the full log"}</button></div>
    ${full !== null && html`<div class="log" data-theme="white-night">${full}</div>`}</div>`;
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

// 006 FR-035: a new issue as you, on GitHub. "Part of" is written as the body's first line, as filed drafts write it.
function NewIssue({ groups, initial, roadmap, onDone, onCancel }) {
  const [repo, setRepo] = useState(initial || "hub");
  const [onBoard, setOnBoard] = useState(Boolean(roadmap));
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [parent, setParent] = useState(null);
  const [picked, setPicked] = useState([]);
  const labels = useLoad(() => (repo ? api(`labels/${repo}`) : Promise.resolve([])), [repo]);
  const act = useAct();
  const partOf = parent ? `${parent.repo}#${parent.number}` : null;
  const toggle = (name) => setPicked((p) => (p.includes(name) ? p.filter((n) => n !== name) : [...p, name]));
  // What was typed becomes the brief of the issue-writer action (005): the planner reads it, and you read its drafts.
  const byClaude = () => {
    const text = [title.trim(), body.trim(), partOf ? `Part of GlassineOS/${partOf}` : "", picked.length ? `Labels to use: ${picked.join(", ")}` : ""].filter(Boolean).join("\n\n");
    launch({ action: "new-issue", repos: [repo], describe: text, from: { view: "Work" } });
    onCancel();
  };
  return html`<h2 id="h-item" style="font-size: 22px; font-weight: 600">New issue</h2>
    <div class="field"><span aria-hidden="true">Repository</span><${RepoPicker} value=${repo} onChange=${(r) => { setRepo(r); setPicked([]); }} groups=${groups} /></div>
    <label class="field"><span>Title</span><input value=${title} onInput=${(e) => setTitle(e.target.value)} /></label>
    <label class="field"><span>Description</span><textarea rows="6" placeholder="Markdown supported" value=${body} onInput=${(e) => setBody(e.target.value)}></textarea></label>
    <div class="field"><span aria-hidden="true">Part of <span class="soft">(optional)</span></span>
      ${parent ? html`<span class="row"><${ItemPill} ...${parent} removable onRemove=${() => setParent(null)} /></span>`
        : html`<${ItemPicker} kind="issue" label="Part of: find an issue" onPick=${(i) => setParent({ kind: "issue", repo: i.repo, number: i.number, title: i.title })} />`}</div>
    <div class="field"><span aria-hidden="true">Labels</span>
      <${Err} text=${labels.error} />${!labels.data && !labels.error && html`<span class="small soft">Loading…</span>`}
      <div class="row" role="group" aria-label="Labels" style="gap: 6px">${(labels.data || []).map((l) => html`<button type="button" class="pill" aria-pressed=${picked.includes(l.name) ? "true" : "false"}
        title=${l.description || ""} onClick=${() => toggle(l.name)}>${l.name}</button>`)}
        ${labels.data && !labels.data.length && html`<span class="small soft">${repo} has no labels.</span>`}</div></div>
    <label class="row small"><input type="checkbox" style="min-height: 0" checked=${onBoard} onChange=${(e) => setOnBoard(e.target.checked)} /> Add to the roadmap</label>
    <${Err} text=${act.error} />
    <div class="row"><button class="gh" disabled=${act.busy || !title.trim() || !repo}
      onClick=${async () => { const r = await act.run(() => post(`issues/${repo}`, { title, body, labels: picked, part_of: partOf, roadmap: onBoard })); if (r) onDone(r); }}>Create on GitHub</button>
      <button class="pen" disabled=${!repo || !(title.trim() || body.trim())} onClick=${byClaude}><${TermIcon} />Let Claude write it instead</button>
      <button onClick=${onCancel}>Cancel</button></div>`;
}

// One input of a workflow, as its type says (006 FR-036). Values go to gh as text.
function WorkflowInput({ input, value, onChange }) {
  const id = `wf-${input.name}`;
  const label = html`<span>${input.name}${input.required ? " *" : ""}${input.description && html` <span class="soft">· ${input.description}</span>`}</span>`;
  if (input.type === "boolean") {
    return html`<label class="row small"><input type="checkbox" style="min-height: 0" checked=${value === "true"} onChange=${(e) => onChange(e.target.checked ? "true" : "false")} />${label}</label>`;
  }
  if (input.type === "choice") {
    return html`<label class="field">${label}<select id=${id} value=${value} onChange=${(e) => onChange(e.target.value)}>
      ${!input.required && html`<option value="">—</option>`}${input.options.map((o) => html`<option value=${o}>${o}</option>`)}</select></label>`;
  }
  return html`<label class="field">${label}<input id=${id} value=${value} inputmode=${input.type === "number" ? "decimal" : undefined}
    placeholder=${input.type === "environment" ? "an environment's name" : ""} onInput=${(e) => onChange(e.target.value)} /></label>`;
}

const inputDefault = (i) => (i.default === undefined ? (i.type === "boolean" ? "false" : i.type === "choice" && i.required ? i.options[0] : "") : String(i.default));

// 006 FR-036, FR-037: a workflow that can be started by hand, as you, with its typed inputs.
function Dispatch({ groups, initial, onDone, onCancel }) {
  const [repo, setRepo] = useState(initial || "");
  const { data, error } = useLoad(() => (repo ? api(`workflows/${repo}`) : Promise.resolve([])), [repo]);
  const [file, setFile] = useState("");
  const [ref, setRef] = useState("main");
  const [shownRef, setShownRef] = useState("main");
  const [values, setValues] = useState({});
  const read = useLoad(() => (repo && file ? api(`workflows/${repo}${params({ inputs: file, ref: shownRef || undefined })}`) : Promise.resolve(null)), [repo, file, shownRef]);
  useEffect(() => { if (read.data) setValues(Object.fromEntries((read.data.inputs || []).map((i) => [i.name, inputDefault(i)]))); }, [read.data]);
  const [confirm, dialog] = useConfirm();
  const act = useAct(onDone);
  const startable = (data || []).filter((w) => w.dispatchable);
  const unread = (data || []).filter((w) => w.dispatchable == null && w.state === "active");
  const inputs = (read.data && read.data.inputs) || [];
  const missing = inputs.filter((i) => i.required && i.type !== "boolean" && !String(values[i.name] || "").trim());
  const off = !file || act.busy || !read.data || read.data.error || read.data.dispatchable === false || missing.length > 0 || shownRef !== ref;
  return html`${dialog}<h2 id="h-item" style="font-size: 22px; font-weight: 600">Run a workflow</h2>
    <${Err} text=${error || act.error} />
    <div class="field"><span aria-hidden="true">Repository</span><${RepoPicker} value=${repo} onChange=${(r) => { setRepo(r); setFile(""); }} groups=${groups} /></div>
    ${repo && data && !startable.length && html`<p role="status" class="notice quiet"><span>No workflow of ${repo} can be started by hand: none has <span class="mono">on: workflow_dispatch</span>.${unread.length ? ` ${count(unread.length, "file")} couldn't be read: ${unread.map((w) => w.name).join(", ")}.` : ""}</span></p>`}
    ${repo && data && startable.length > 0 && unread.length > 0 && html`<p role="status" class="small soft">${count(unread.length, "workflow")} of ${repo} can't be listed here: ${unread.map((w) => w.inputs_error || `couldn't read ${w.name}`).join("; ")}.</p>`}
    ${(!repo || !data || startable.length > 0) && html`
      <label class="field"><span>Workflow</span><select value=${file} disabled=${!repo || !data} onChange=${(e) => setFile(e.target.value)}>
        <option value="">Choose…</option>${startable.map((w) => html`<option value=${w.path.split("/").pop()}>${w.name}</option>`)}</select></label>
      <label class="field"><span>Branch or tag</span><span class="row" style="gap: 6px; flex-wrap: nowrap"><input value=${ref} onInput=${(e) => setRef(e.target.value)} />
        <button type="button" disabled=${!file || ref === shownRef || !ref.trim()} onClick=${() => setShownRef(ref.trim())}>Read its inputs</button></span></label>
      ${file && read.loading && html`<p class="small soft">Reading ${file} at ${shownRef}…</p>`}
      ${read.data && read.data.error && html`<p role="status" class="small"><b>${read.data.error}.</b> The form can't show its inputs.</p>`}
      ${read.data && read.data.dispatchable === false && html`<p role="status" class="small">At ${shownRef}, ${file} can't be started by hand.</p>`}
      ${read.data && !read.data.error && read.data.dispatchable && (inputs.length
        ? html`<fieldset class="stack" style="gap: 8px; border: 0; padding: 0"><legend class="eyebrow">Inputs</legend>${inputs.map((i) => html`<${WorkflowInput} key=${i.name} input=${i}
            value=${values[i.name] ?? ""} onChange=${(v) => setValues((x) => ({ ...x, [i.name]: v }))} />`)}</fieldset>`
        : html`<p class="small soft">It takes no inputs.</p>`)}`}
    <div class="row"><button class="gh" disabled=${off} title=${shownRef !== ref ? "Read the inputs at this branch first" : missing.length ? `Needs ${missing.map((i) => i.name).join(", ")}` : ""} onClick=${() => confirm(
      { title: "Start this workflow?", text: `${file} of ${repo} on ${ref}. Some workflows publish things.`, label: "Start" },
      () => act.run(() => post(`workflows/${repo}/${file}/dispatch`, { ref, inputs: Object.fromEntries(Object.entries(values).filter(([, v]) => v !== "")) })),
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

const sizeWords = (p) => (p.additions == null ? "" : `+${p.additions} −${p.deletions}`);
const spanWords = (from, to) => {
  const s = Math.round((new Date(to) - new Date(from)) / 1000);
  return !from || !to || !(s >= 0) ? "" : s < 60 ? `${s}s` : s < 3600 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
};
const partWords = (r) => (r.part_of ? `Part of ${r.part_of}` : "");
const join = (parts) => parts.filter(Boolean).join(" · ");

// A row of Work (006 FR-006): its sub-line, its state, and the facts its one blue action is chosen by (FR-007).
const ROWS = {
  issues: (i) => ({
    key: `${i.repo}#${i.number}`, repo: i.repo, number: i.number, ref: `${i.repo}#${i.number}`, title: i.title,
    sub: join([partWords(i), i.author && i.author.login, i.comments ? count(i.comments, "comment") : "", i.labels.map((l) => l.name).join(", ")]),
    state: i.state === "OPEN" ? "Open" : "Closed", badge: i.state === "OPEN" ? "" : "dim", pill: pillState("issue", i), at: i.updatedAt, object: "issue",
    labels: i.labels.map((l) => l.name), startable: i.state === "OPEN", facts: { untriaged: i.state === "OPEN" && !i.labels.length, openThreads: 0, reviews: 0 },
  }),
  prs: (p) => {
    const changes = p.reviewDecision === "CHANGES_REQUESTED";
    return {
      key: `${p.repo}#${p.number}`, repo: p.repo, number: p.number, ref: `${p.repo}#${p.number}`, title: p.title,
      sub: join([partWords(p), sizeWords(p), p.author && p.author.login, `${p.headRefName} → ${p.baseRefName}`]),
      agent: p.headRefName.startsWith("agent/"), object: "pr", pill: pillState("pr", p), at: p.updatedAt, labels: p.labels.map((l) => l.name), startable: p.state === "OPEN",
      state: p.state !== "OPEN" ? (p.state === "MERGED" ? "Merged" : "Closed") : p.isDraft ? "Draft" : p.checks === "failing" ? "Failing" : changes ? "Changes asked" : p.checks === "pending" ? "Checks" : p.checks === "passing" ? "Ready" : "Open",
      badge: p.state !== "OPEN" ? "dim" : p.checks === "failing" ? "bad" : "",
      icon: p.state !== "OPEN" ? "pass" : p.checks === "failing" ? "fail" : p.checks === "pending" ? "run" : p.checks === "passing" ? "pass" : "open",
      facts: { failing: p.state === "OPEN" && p.checks === "failing", changesRequested: changes, openThreads: 0, reviews: changes ? 1 : 0 },
    };
  },
  actions: (r) => ({
    key: `${r.repo}/${r.databaseId}`, repo: r.repo, number: r.databaseId, workflow: r.workflowName, ref: `${r.workflowName} #${r.databaseId}`, title: `${r.repo} · ${r.displayTitle}`,
    sub: join([`${r.event} on ${r.headBranch}`, (r.headSha || "").slice(0, 7), r.status === "completed" ? spanWords(r.createdAt, r.updatedAt) : "running"]),
    agent: (r.headBranch || "").startsWith("agent/"), object: "run", pill: pillState("run", r), at: r.createdAt, labels: [], startable: r.status === "completed",
    state: r.status !== "completed" ? "Running" : r.conclusion === "success" ? "Passed" : r.conclusion === "failure" ? "Failed" : r.conclusion || "Done",
    badge: r.status !== "completed" ? "" : r.conclusion === "failure" ? "bad" : r.conclusion === "success" ? "" : "dim",
    icon: r.status !== "completed" ? "run" : r.conclusion === "failure" ? "fail" : r.conclusion === "success" ? "pass" : "open",
    facts: { failing: r.status === "completed" && r.conclusion === "failure", openThreads: 0, reviews: 0 },
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

// 006 FR-003–FR-005: the groups of each tab, in the order shown. session: the first session on the row, if any.
const NEEDS = {
  prs: { order: ["Needs you", "From agent sessions", "Everything else"],
    of: (r, session) => (session && session.agent.waiting) || r.state === "Failing" || r.state === "Ready" || r.state === "Changes asked" ? "Needs you"
      : r.agent || session ? "From agent sessions" : "Everything else" },
  issues: { order: ["Untriaged", "In sessions", "Backlog"], of: (r, session) => (session ? "In sessions" : r.facts.untriaged ? "Untriaged" : "Backlog") },
  actions: { order: ["Failed", "Running", "Recent"], of: (r) => (r.icon === "fail" ? "Failed" : r.icon === "run" ? "Running" : "Recent") },
};
const groupOf = (tab, row, session) => NEEDS[tab].of(row, session);

function readWorkFilter() {
  try { return JSON.parse(sessionStorage.getItem("work-filter")) || {}; } catch { return {}; }
}

// 006 FR-001: the repository last chosen on Work, per viewer. The address wins when it names one.
const WORK_REPO_KEY = "work-repo";
function readWorkRepo() {
  try { return localStorage.getItem(WORK_REPO_KEY) || ""; } catch { return ""; }
}
function writeWorkRepo(name) {
  try { localStorage.setItem(WORK_REPO_KEY, name || ""); } catch { /* it only helps */ }
}

const MAX_ROW_CHIPS = 3;
const PAGE = 50; // rows asked for at a time (001 FR-019); "Load more" asks for the next ones
const KIND_OF_TAB = { issues: "issue", prs: "pr", actions: "run" };

function WorkRow({ row, tab, scope, sessions, action }) {
  const open = hash("work", { tab, repo: scope, at: row.repo, item: row.number });
  const kind = KIND_OF_TAB[tab];
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
    <span class=${`state badge ${row.badge || ""}`}>${row.state}</span><span class="age">${age(row.at)}</span>
    ${action && html`<button class="start" title=${`${action.summary} Opens Launch: the planner runs first, and you read its plan. ${action.ceiling}`} onClick=${launchIt}><${TermIcon} />${action.title}</button>`}
  </div>`;
}

// Work's tabs. The queue is its own view of the pull requests, so it has the page to itself (006 FR-009).
function Work({ query, asks }) {
  return query.tab === "queue" ? html`<${WorkQueue} />` : html`<${WorkLists} query=${query} asks=${asks} />`;
}

// Whether a session is drawn embedded in the Work item `here` (owner/repo#n) or sits in the background there.
// moved: what was set on this page, keyed `${name}@${here}`, so a move on item A says nothing about item B;
// else the view hubd stored, which is embedded only for the item it was stored for.
function embeddedPhase(session, here, moved) {
  if (!session) return null;
  const set = moved[`${session.name}@${here}`];
  if (set) return set;
  const stored = session.agent && session.agent.view;
  return stored && stored.mode === "embedded" && stored.where === "Work" && (!stored.ref || stored.ref === here) ? "embedded" : "background";
}

// 006 FR-002: the kinds, pull requests first. The queue is a view of the pull requests (FR-009).
const WORK_TABS = [["prs", "Pull requests"], ["issues", "Issues"], ["actions", "Runs"], ["queue", "Queue"]];

function WorkLists({ query, asks }) {
  const overview = useLoad(() => api("overview"), []);
  const sessions = useSessions();
  // What the address says, so an item can be linked to and Back returns to the list as it was.
  const tab = query.tab || "prs";
  const scope = query.repo || "";
  const go = (patch) => { location.hash = hash("work", { tab, repo: scope, ...patch }); };
  // 006 FR-001: with no repository in the address, the one you last chose here; "All repositories" is remembered too.
  useEffect(() => {
    const kept = readWorkRepo();
    if (!query.repo && kept && !query.item) location.replace(hash("work", { ...query, tab, repo: kept }));
  }, []);
  const chooseRepo = (name) => { writeWorkRepo(name); go({ repo: name || undefined }); };
  // In this tab of the browser, so a reload keeps your list and k / j still walk it.
  const kept = useRef(readWorkFilter()).current;
  const [states, setStates] = useState({ issues: "open", prs: "open", ...kept.states, ...(query.status ? { actions: query.status } : {}) });
  const [groupBy, setGroupBy] = useState(kept.groupBy || "needs");
  const [search, setSearch] = useState(kept.applied || "");
  const [applied, setApplied] = useState(kept.applied || "");
  useEffect(() => { try { sessionStorage.setItem("work-filter", JSON.stringify({ states, groupBy, applied })); } catch { /* it only helps */ } }, [states, groupBy, applied]);
  const [byMeaning, setByMeaning] = useState(false);
  const [panel, setPanel] = useState(query.new === "1" ? "new" : null);
  const [notice, setNotice] = useState(null);
  const [phases, setPhases] = useState({}); // `${session name}@${item}` → embedded or background, as moved on this page; else its stored view
  const [keptCheckout, setKeptCheckout] = useState(null); // { ref, path }: Stop ended a session whose checkout holds work that isn't on GitHub
  useEffect(() => { if (query.new === "1") setPanel("new"); }, [query.new]);
  const groups = overview.data ? overview.data.groups : [];
  const filter = parseFilter(applied);
  const repo = filter.repo || scope;
  const state = filter.state || states[tab];
  const assignee = filter.assignee === "me" ? "@me" : filter.assignee || "";
  // 001 FR-019: one page of rows, and more on request. Back to one page when what's listed changes.
  const [pages, setPages] = useState(1);
  useEffect(() => setPages(1), [tab, repo, state, assignee, filter.words]);
  const asked = tab === "actions" ? Math.ceil(PAGE / 2) * pages : PAGE * pages;
  const load = async () => {
    if (tab === "issues") return { tab, rows: await api(`issues${params({ repo, state, search: filter.words, assignee, limit: asked })}`) };
    return { tab, rows: await (tab === "prs" ? api(`prs${params({ repo, state, limit: asked })}`) : api(`runs${params({ repo, status: state, limit: asked })}`)) };
  };
  const loaded = useLoad(load, [tab, repo, state, assignee, filter.words, asked], 20000);
  const { error, loading, reload } = loaded;
  // The list of the tab you just left is still here until the new one arrives, and has other fields.
  const data = loaded.data && loaded.data.tab === tab ? loaded.data.rows : null;
  const offered = useLoad(() => api(`agents/actions${params({ object: KIND_OF_TAB[tab] })}`).catch(() => []), [tab]);
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
  const layerOf = new Map(groups.flatMap((g) => g.repos.map((r) => [r.name, g.title])));
  // 006 FR-007: the one blue action of a row, by the rule the item page uses. Plain sessions (no planner) aren't offered here.
  const startFor = (r) => (r.startable ? bestAction(KIND_OF_TAB[tab], r.facts, offeredFor(offered.data || [], r.facts).filter((a) => a.plan !== false)) : null);
  const sections = () => {
    if (groupBy === "none") return [[null, rows]];
    const keyOf = groupBy === "repo" ? (r) => r.repo : groupBy === "layer" ? (r) => layerOf.get(r.repo) || "Unplaced" : (r) => groupOf(tab, r, sessionOf(r));
    const by = new Map(groupBy === "needs" ? NEEDS[tab].order.map((k) => [k, []]) : []);
    for (const r of rows) by.set(keyOf(r), [...(by.get(keyOf(r)) || []), r]);
    return [...by.entries()].filter(([, v]) => v.length);
  };
  const shown = sections().flatMap(([, v]) => v); // k and j follow the order on the page
  const itemRepo = query.at || query.repo;
  const itemNumber = query.item ? Number(query.item) : null;
  const current = itemNumber && itemRepo ? { repo: itemRepo, number: itemNumber, object: KIND_OF_TAB[tab], key: `${itemRepo}#${itemNumber}` } : null;
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
  // 006 FR-002: counts for the repository chosen, or all of them. Open issues and pull requests come from the overview;
  // runs only from the list on screen, as nothing counts them all without asking each repository.
  const tabCount = { prs: scoped ? scoped.prs : counts && counts.prs, issues: scoped ? scoped.issues : counts && counts.issues,
    actions: tab === "actions" && data ? `${data.length}${data.length >= asked ? "+" : ""}` : null, queue: null };
  const TABS = WORK_TABS.map(([id, label]) => [id, label, tabCount[id]]);
  const stateWord = (STATES[tab].find(([v]) => v === state) || [state, state])[1];
  if (current) {
    const here = `${current.repo}#${current.number}`;
    const on = sessionsOn(current, list);
    // Where each session on the item shows: as moved on this page for this item, else its stored view (embeddedPhase).
    const phaseOf = (s) => embeddedPhase(s, here, phases);
    // Moved here: shown so at once, and kept by hubd for the next page that draws it.
    const place = (name, mode) => {
      const key = `${name}@${here}`;
      setNotice(null);
      setPhases((p) => ({ ...p, [key]: mode }));
      post("agents/view", { name, mode, where: "Work", ref: here }).then(() => sessions.reload(), (e) => {
        // Not stored, so not shown: back to what hubd has, and say so.
        setPhases((p) => { const { [key]: _, ...rest } = p; return rest; });
        setNotice(`Couldn't move ${name} to ${mode === "embedded" ? "this item" : "the background"}: ${e.message}`);
      });
    };
    const frame = {
      launchRow: ({ kind, facts }) => html`<${LaunchRow} key=${current.key} kind=${kind} repo=${current.repo} number=${current.number} facts=${facts} road=${kind === "issue" && query.road === "1"} />`,
      sessions: ({ kind, facts }) => html`<${SessionsOn} key=${current.key} kind=${kind} repo=${current.repo} number=${current.number} facts=${facts} sessions=${on}
        phaseOf=${phaseOf} place=${place} setPhase=${(name, m) => setPhases((p) => ({ ...p, [`${name}@${here}`]: m }))} asks=${asks} onReload=${() => sessions.reload()}
        onEnded=${(r) => { setKeptCheckout(r && r.kept ? { ref: here, path: r.kept } : null); sessions.reload(); }} />
        ${keptCheckout && keptCheckout.ref === here && html`<div role="status" class="notice quiet"><span>That session had work that isn't on GitHub, so its checkout stays at <code>${keptCheckout.path}</code>.</span></div>`}`,
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
  const layer = scoped ? layerOf.get(scoped.name) : null;
  const more = data && !found && data.length >= asked;
  return html`<main class="page close">
    <h1 class="sr">Work</h1>
    <div class="row" style="gap: 10px 14px; align-items: flex-start"><span class="eyebrow soft" style="padding-top: 10px">Repository</span>
      <${RepoPicker} value=${scope} allowAll onChange=${chooseRepo} groups=${groups} />
      <span class="grow"></span>
      <button class="pen" onClick=${() => launch({ repos: repo ? [repo] : undefined, from: { view: "Work" } })}><${TermIcon} />${repo ? `New work in ${repo}…` : "New work…"}</button>
      <${GhActions} kind="work" data=${{ url: `https://github.com/GlassineOS${repo ? `/${repo}` : ""}`, tab }} onPanel=${setPanel} onDone=${() => {}} /></div>
    <p style="font-size: 17px; line-height: 1.4"><span class="mono" style="font-weight: 600">${repo ? `GlassineOS/${repo}` : `GlassineOS · all ${groups.flatMap((g) => g.repos).length} repositories`}</span>
      <span class="soft"> · ${repo ? (layer || "") : groupBy === "needs" ? "grouped by what needs you" : "all"}</span></p>
    ${panel && html`<div class="panel">${panel === "new" ? html`<${NewIssue} groups=${groups} initial=${repo || query.repo} roadmap=${query.roadmap === "1"} onCancel=${() => setPanel(null)}
        onDone=${(r) => { setPanel(null); reload(); setNotice(r.roadmap_error ? `Created, but not added to the roadmap: ${r.roadmap_error}` : null); go({ tab: "issues", at: r.repo, item: r.number, new: undefined, roadmap: undefined }); }} />`
      : html`<${Dispatch} key=${repo} groups=${groups} initial=${repo} onCancel=${() => setPanel(null)} onDone=${() => { setPanel(null); go({ tab: "actions" }); reload(); }} />`}</div>`}
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
    ${data && html`<div class="row small soft" role="status" style="gap: 6px 12px"><span>${count(rows.length, "row")} listed${more ? ", the newest first: there are more" : ""}.</span>
      ${more && html`<button class="link" disabled=${loading} onClick=${() => setPages(pages + 1)}>${loading ? "Loading…" : "Load more"}</button>`}</div>`}
    ${rows.length > 0 && html`<p class="small soft">Open an item to work on it full width, and k / j steps through this list from there. The blue button on a row opens Launch with its most likely Claude action.</p>`}
  </main>`;
}

// --- Knowledge -----------------------------------------------------------------------------------
// 008 FR-002: the three domains; Code is shown, and can't be chosen until it is indexed.
const KN_DOMAINS = [["docs", "Docs"], ["work", "Work items"], ["code", "Code"]];
const KN_PLANNED = ["code"];
const KN_TRY = ["how do I get back into recovery?", "why LUT version 3", "which repositories does the Steward read?", "e-ink refresh modes"];
const KN_KIND = { docs: "Docs page", issue: "Issue", pr: "Pull request" };
const KN_INDEX = { docs: "Docs", work: "Work items", code: "Code" };
const KN_STATE = { ready: "", indexing: "dim", planned: "dim", failed: "bad" };
const KN_LAYOUTS = [["ranked", "Ranked"], ["grouped", "By repository"]];
const KN_DOCS_SITE = "docs.glassine.org";

// What Knowledge searched for, from the address: a reload or a link gives the same page, and the Steward's
// panel can see the chosen repositories (010 FR-004). Pins and the flyout stay on the page.
function readKnowledge(q) {
  const list = (v) => (v || "").split(",").filter(Boolean);
  const domains = list(q.domains).filter((d) => KN_DOMAINS.some(([id]) => id === d) && !KN_PLANNED.includes(d));
  return { q: (q.q || "").slice(0, 500), mode: q.mode === "exact" ? "exact" : "meaning", domains: domains.length ? domains : ["docs", "work"],
    repos: seenRepos(q.repos), open: q.open === "1", layout: q.layout === "grouped" ? "grouped" : "ranked" };
}
const knowledgeHash = (k) => hash("knowledge", { q: k.q, mode: k.mode === "exact" ? "exact" : undefined,
  domains: k.domains.join(",") === "docs,work" ? undefined : k.domains.join(","), repos: k.repos.join(","), open: k.open ? "1" : undefined,
  layout: k.layout === "grouped" ? "grouped" : undefined });

// 008 FR-004: the matched words marked, from hubd's own spans, never by HTML in the text.
function Marked({ text, marks }) {
  const parts = [];
  let at = 0;
  for (const [a, b] of marks || []) {
    if (a < at || b > text.length) continue;
    if (a > at) parts.push(text.slice(at, a));
    parts.push(html`<mark>${text.slice(a, b)}</mark>`);
    at = b;
  }
  parts.push(text.slice(at));
  return parts;
}

const pinOf = (r) => (r.domain === "docs" ? { kind: "docs", label: r.link } : { kind: "ref", label: `${r.repo}#${r.number}` });

function KnowledgeResult({ r, sessions, pinned, onPin }) {
  const item = r.domain === "work" ? { kind: r.kind, repo: r.repo, number: r.number } : null;
  const on = item ? sessionsOn(item, sessions) : [];
  const open = item ? itemHref(item) : r.link;
  return html`<li class="hit kn-hit">
    <div class="row" style="gap: 4px 10px; align-items: baseline">
      <span class="label" style="padding-right: 8px">${KN_KIND[r.kind] || r.kind}</span>
      ${item ? html`<${ItemPill} ...${item} state=${pillState(r.kind, r)} href=${open} />` : html`<span class="mono soft small">${KN_DOCS_SITE}</span>`}
      <b style="flex: 1 1 240px; min-width: 0; overflow-wrap: anywhere"><${Marked} text=${r.title} marks=${r.title_marks} /></b>
      ${r.score == null
        ? html`<span class="small soft mono" title="Found by its words alone: no meaning score to show">words ${Math.round((r.words || 0) * 100)}%</span>`
        : html`<span class="small soft mono" title="How close it is in meaning (cosine)">score ${r.score.toFixed(2)}</span>`}</div>
    ${r.snippet && html`<p style="overflow-wrap: anywhere"><${Marked} text=${r.snippet} marks=${r.marks} /></p>`}
    <div class="row" style="gap: 6px 10px">
      ${on.map((s) => html`<${SessionChip} key=${s.name} session=${s} href=${open} />`)}
      ${item ? html`<a class="button" href=${open}>Open</a>` : html`<a class="button" href=${r.link} target="_blank" rel="noreferrer noopener">Open</a>`}
      <button aria-pressed=${pinned ? "true" : "false"} onClick=${onPin}>${pinned ? "Pinned ✓" : "Pin as context"}</button></div></li>`;
}

// 008 FR-009: each index with its state and age, and what starts it again.
function KnowledgeIndexes() {
  const { data, error, reload } = useLoad(() => api("knowledge/indexes"), [], 60000);
  const act = useAct(reload);
  const press = { reindex: ["Run docs CI now", () => post("docs/reindex")], sync: ["Ingest now", () => post("work/sync")] };
  return html`<section class="stack" style="gap: 8px" aria-labelledby="kn-idx"><h3 id="kn-idx" class="eyebrow">Indexes</h3>
    <${Err} text=${error || act.error} />
    ${data && html`<ul class="stack" style="gap: 10px">${data.map((i) => html`<li class="stack tight">
      <div class="row" style="gap: 8px"><b>${KN_INDEX[i.id] || i.id}</b><span class="badge ${KN_STATE[i.state] || ""}">${i.state}${i.stale ? " · stale" : ""}</span>
        ${i.age && html`<span class="small soft">${ago(i.age)}</span>`}${i.size != null && html`<span class="small soft">${i.size.toLocaleString()} ${i.id === "docs" ? "passages" : "issues and pull requests"}</span>`}</div>
      <span class="small">${i.says}</span>
      ${press[i.action] && html`<button style="align-self: flex-start" disabled=${act.busy || !i.can_act} title=${i.can_act ? "" : "Nothing to do now"}
        onClick=${() => act.run(press[i.action][1])}>${press[i.action][0]}</button>`}</li>`)}</ul>`}</section>`;
}

// 008 FR-008: kept reports, newest first, 20 then more; each opens, or is followed up in Launch.
function KnowledgeReports() {
  const [pages, setPages] = useState([]);
  const [open, setOpen] = useState(null);
  const first = useLoad(() => api(`results${params({ type: "report", kept: "1" })}`), []);
  const more = useAct();
  const rows = [...((first.data && first.data.results) || []), ...pages];
  const last = rows[rows.length - 1];
  // 008 FR-008: the report goes by its id, which only a research session can read (read_report): its text, which can be
  // private, never sits in Launch, where the action could be switched to one that posts.
  const followUp = (r) => launch({ action: "knowledge-research", notes: `Follow-up on the kept report ${r.id}: ${(r.payload || {}).question || ""}`.slice(0, 4000),
    pins: [{ kind: "report", label: r.id }], from: { view: "Knowledge" } });
  return html`<section class="stack" style="gap: 8px" aria-labelledby="kn-rep"><h3 id="kn-rep" class="eyebrow">Research reports</h3>
    <${Err} text=${first.error || more.error} />
    ${first.data && !rows.length && html`<p class="small soft">No reports kept yet. A research session's report is kept when you press "Save to Knowledge" on it.</p>`}
    <ul class="stack" style="gap: 8px">${rows.map((r) => html`<li class="stack tight" key=${r.id}>
      <b style="overflow-wrap: anywhere">${(r.payload || {}).question || r.id}</b>
      <span class="small soft">${r.session} · ${whenAgo(r.made)}</span>
      <div class="row" style="gap: 6px"><button aria-expanded=${open === r.id ? "true" : "false"} onClick=${() => setOpen(open === r.id ? null : r.id)}>${open === r.id ? "Close" : "Open"}</button>
        <button onClick=${() => followUp(r)}>Follow up…</button></div>
      ${open === r.id && html`<${ResultView} r=${r} where="Knowledge" />`}</li>`)}</ul>
    ${first.data && first.data.results.length >= 20 && (pages.length === 0 || pages.length % 20 === 0) && last && html`<button class="link" style="align-self: flex-start" disabled=${more.busy}
      onClick=${() => more.run(async () => { const r = await api(`results${params({ type: "report", kept: "1", after: last.id })}`); setPages([...pages, ...r.results]); })}>More reports</button>`}</section>`;
}

// 008 FR-007: the question, the scope and the pins, then Launch's research action. It needs no repository.
function ResearchFlyout({ k, pins, onPins, onClose }) {
  const ref = useRef();
  const [question, setQuestion] = useState(k.q);
  useModal(ref);
  const scope = `${k.domains.map((d) => KN_INDEX[d]).join(" and ")}${k.repos.length ? `, in ${k.repos.join(", ")}` : ", every repository"}${k.open && k.domains.includes("work") ? ", open work items only" : ""}`;
  const plan = () => {
    launch({ action: "knowledge-research", notes: `Question: ${question.trim()}\nScope: ${scope}`.slice(0, 4000), pins: pins.slice(0, 12), from: { view: "Knowledge" } });
    ref.current.close();
  };
  return html`<dialog class="flyout" ref=${ref} onClose=${onClose} aria-labelledby="kn-fly">
    <div class="row" style="justify-content: space-between"><h2 id="kn-fly">Research this</h2><button class="plain" onClick=${() => ref.current.close()}>Close</button></div>
    <div class="stack" style="gap: 18px">
      <label class="field"><span>Question</span><textarea rows="3" maxlength="2000" value=${question} onInput=${(e) => setQuestion(e.target.value)} /></label>
      <div class="stack tight"><span class="eyebrow">Scope</span><span class="small">${scope}</span></div>
      <div class="stack tight"><span class="eyebrow">Pins · ${pins.length || "none"}</span>
        ${pins.length > 0 ? html`<ul class="row" style="gap: 6px">${pins.map((p) => html`<li class="label"><span class="soft">${PIN_WORDS[p.kind]}</span> <span class="mono" style="overflow-wrap: anywhere">${p.label}</span>
          <button aria-label=${`Remove ${p.label}`} onClick=${() => onPins(pins.filter((x) => x !== p))}>×</button></li>`)}</ul>`
          : html`<span class="small soft">Pin results as context, or plan without them.</span>`}</div>
      <div class="row"><button class="primary" disabled=${!question.trim()} onClick=${plan}>Plan a research session…</button>
        <span class="small soft">Opens Launch. The session reads only, hands in a report and posts nothing.</span></div>
      <${KnowledgeReports} />
      <${KnowledgeIndexes} /></div></dialog>`;
}

function Knowledge({ query }) {
  const k = readKnowledge(query);
  const go = (patch) => { location.hash = knowledgeHash({ ...k, ...patch }); };
  const [typed, setTyped] = useState(k.q);
  useEffect(() => setTyped(k.q), [k.q]);
  const [pins, setPins] = useState([]);
  const [flyout, setFlyout] = useState(false);
  const sessions = useSessions();
  const overview = useLoad(() => api("overview"), []);
  const groups = overview.data ? overview.data.groups : [];
  const found = useLoad(() => (k.q ? api(`knowledge/search${params({ q: k.q, mode: k.mode, domains: k.domains.join(","), repos: k.repos.join(","), open: k.open ? "1" : "" })}`) : Promise.resolve(null)),
    [k.q, k.mode, k.domains.join(), k.repos.join(), k.open]);
  const data = found.data;
  const results = data ? data.results : [];
  const pinned = (r) => pins.some((p) => p.label === pinOf(r).label);
  const togglePin = (r) => setPins(pinned(r) ? pins.filter((p) => p.label !== pinOf(r).label) : pins.length >= 12 ? pins : [...pins, pinOf(r)]);
  const toggleDomain = (d) => { const next = k.domains.includes(d) ? k.domains.filter((x) => x !== d) : [...k.domains, d]; if (next.length) go({ domains: next }); };
  const card = (r) => html`<${KnowledgeResult} key=${pinOf(r).label} r=${r} sessions=${sessions.data} pinned=${pinned(r)} onPin=${() => togglePin(r)} />`;
  const grouped = () => {
    const by = new Map();
    for (const r of results) { const g = r.repo || KN_DOCS_SITE; by.set(g, [...(by.get(g) || []), r]); }
    return [...by].map(([g, rows]) => html`<section class="stack" style="gap: 6px" aria-label=${g}><h3 class="mono" style="font-size: 15px">${g} (${rows.length})</h3><ol>${rows.map(card)}</ol></section>`);
  };
  const failed = data ? data.domains.filter((d) => !d.ok) : [];
  return html`<main class="page"><div class="stack" style="gap: 20px">
    <div class="row" style="justify-content: space-between; align-items: flex-end">
      <div class="stack tight"><${Eyebrow} soft>Docs, work items and code<//><h1 id="h-search">Knowledge</h1></div>
      <button class="primary" onClick=${() => setFlyout(true)}>Research this…${pins.length ? ` (${count(pins.length, "pin")})` : ""}</button></div>
    <form role="search" class="row" style="gap: 12px" onSubmit=${(e) => { e.preventDefault(); if (typed.trim()) go({ q: typed.trim() }); }}>
      <div class="searchbox big" style="flex: 1 1 360px"><${SearchIcon} /><label class="sr" for="kn-q">Search docs, work items and code</label>
        <input id="kn-q" type="search" maxlength="500" placeholder="Ask in plain words, or type the exact words" value=${typed} onInput=${(e) => setTyped(e.target.value)} /></div>
      <button class="primary" style="min-height: 52px; padding: 0 20px" disabled=${!typed.trim()}>Search</button></form>
    <div class="row" style="gap: 10px 18px; align-items: center">
      <div role="radiogroup" aria-label="Match by" class="seg">${[["meaning", "Meaning"], ["exact", "Exact words"]].map(([m, w]) => html`<button role="radio" aria-checked=${k.mode === m ? "true" : "false"} onClick=${() => go({ mode: m })}>${w}</button>`)}</div>
      <div role="group" aria-label="Domains" class="row" style="gap: 6px">${KN_DOMAINS.map(([d, w]) => KN_PLANNED.includes(d)
        ? html`<button class="pill" disabled aria-pressed="false" title="Not indexed yet">${w} · planned</button>`
        : html`<button class="pill" aria-pressed=${k.domains.includes(d) ? "true" : "false"} onClick=${() => toggleDomain(d)}>${w}</button>`)}</div>
      <${RepoPicker} many allowAll value=${k.repos} onChange=${(v) => go({ repos: v || [] })} groups=${groups} label="Repositories" />
      <label class="row small" style="gap: 6px"><input type="checkbox" checked=${k.open} disabled=${!k.domains.includes("work")} onChange=${(e) => go({ open: e.target.checked })} />Open only <span class="soft">(work items)</span></label>
      <div role="radiogroup" aria-label="Layout" class="seg">${KN_LAYOUTS.map(([l, w]) => html`<button role="radio" aria-checked=${k.layout === l ? "true" : "false"} onClick=${() => go({ layout: l })}>${w}</button>`)}</div></div>
    ${k.repos.length > 0 && k.domains.includes("docs") && html`<p class="small soft">Repositories narrow the work items. The docs are one site, ${KN_DOCS_SITE}, and are searched whole.</p>`}
    ${!k.q && html`<div class="row" style="gap: 6px"><span class="small soft">Try:</span>${KN_TRY.map((t) => html`<button class="pill" onClick=${() => go({ q: t })}>${t}</button>`)}</div>`}
    <${Err} text=${found.error} />
    ${failed.map((d) => html`<p class="small" role="status"><b>${KN_INDEX[d.id]}</b> couldn't be searched: ${d.error}</p>`)}
    ${k.q && found.loading && html`<p class="soft small" role="status">Searching… the first search by meaning may download the model once.</p>`}
    ${data && !data.good && html`<div class="panel stack" style="gap: 8px; padding: 16px" role="status">
      <b>${results.length ? "Nothing here answers it well." : "Nothing found."}</b>
      <span class="small">That doesn't prove it isn't written down. A research session can look further and hand in a report.</span>
      <button class="primary" style="align-self: flex-start" onClick=${() => setFlyout(true)}>Research this…${pins.length ? ` (${count(pins.length, "pin")})` : ""}</button></div>`}
    ${data && results.length > 0 && html`<span class="small soft" role="status">${count(results.length, "result")}${data.mode === "exact" ? ", each with every word" : ", best match first"}</span>`}
    ${results.length > 0 && (k.layout === "grouped" ? grouped() : html`<ol>${results.map(card)}</ol>`)}
    ${flyout && html`<${ResearchFlyout} k=${k} pins=${pins} onPins=${setPins} onClose=${() => setFlyout(false)} />`}
  </div></main>`;
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
// Terminals are on night paper in both schemes: their element carries data-theme="white-night",
// and xterm takes its colours and font from that element's tokens.
const terminalLook = (el) => {
  const cs = getComputedStyle(el), token = (name) => cs.getPropertyValue(name).trim();
  return { fontFamily: token("--font-mono"), theme: { background: token("--paper"), foreground: token("--ink"), cursor: token("--ink") } };
};

function TerminalView({ name, onGone, focusRef, quiet }) {
  const box = useRef();
  const [note, setNote] = useState("Connecting…");
  const [copied, setCopied] = useState("");
  const [typing, setTyping] = useState(true);
  useEffect(() => {
    const term = new Terminal({ cursorBlink: !reducedMotion(), fontSize: 14, scrollback: 5000, ...terminalLook(box.current) });
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
      // 001 FR-016: the terminal takes Tab for itself, so F6 and Shift+F6 leave it for the next or previous control.
      if (e.key === "F6") {
        if (e.type === "keydown") focusPast(term.textarea, e.shiftKey ? -1 : 1);
        e.preventDefault();
        return false;
      }
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
    <div key="term" class="term" data-theme="white-night" ref=${box} role="group" aria-label="Terminal. F6 or Shift+F6 leaves it." title="F6 or Shift+F6 leaves the terminal"></div>
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
  // #36 review, 4: the list keeps the last repository's folders while the next one loads, so a switch clears the folder
  // and Start waits for the new list: a shell never starts in the repository you just left.
  const loadingPlaces = Boolean(repo) && places.loading;
  return html`<div class="panel" style="padding: 14px; gap: 10px">
    <${Err} text=${act.error || places.error} />
    <label class="field"><span>Name</span><input value=${name} onInput=${(e) => setName(e.target.value)} /></label>
    <${RepoPicker} value=${repo} onChange=${(r) => { setRepo(r); setCwd(""); if (!name.trim() && r) setName(`shell-${r.replace(/^\./, "")}`); }} groups=${groups} label="Repository" />
    ${repo && html`<label class="field"><span>Worktree</span><select value=${cwd} onChange=${(e) => setCwd(e.target.value)}>
      ${(places.data || []).map((w) => html`<option value=${w.path}>${w.label} · ${w.path}</option>`)}
      <option value="">home</option></select></label>
      ${places.data && !places.data.length && html`<span class="small soft">No checkout of ${repo} in the workspace yet: the shell starts in your home.</span>`}`}
    <label class="field"><span>Command</span><input placeholder="your shell" value=${command} onInput=${(e) => setCommand(e.target.value)} /></label>
    ${loadingPlaces && html`<span role="status" class="small soft">Finding ${repo}'s worktrees…</span>`}
    <div class="row"><button class="primary" disabled=${act.busy || !name.trim() || loadingPlaces} onClick=${async () => {
      const r = await act.run(() => post("shells", { name, cwd: cwd || null, command: command || null }));
      if (r) onDone(name);
    }}>Start</button><button onClick=${onCancel}>Cancel</button></div></div>`;
}

const shortModel = (m) => (m ? m[0].toUpperCase() + m.slice(1) : "");

// --- the design view (011 FR-010–FR-019) ---------------------------------------------------------------
// A live picture of a browser on the host, on the renderer's preview of a design session's worktree. This page only
// draws the PNG frames hubd relays and sends back clicks, touches, the wheel and keys: a board's code runs in that
// host browser, never here (FR-012). Nothing from the renderer is put into the page as markup.
const DESIGN_ESC_TWICE = 800; // ms between the two Escs that leave the picture
// The scale a frame is drawn at (FR-013): 100 % when it fits or when asked for, else what fits the box.
function designScale(frame, box, actual) {
  if (!frame || !frame.width || !frame.height || actual) return 1;
  const across = box.width > 0 ? box.width / frame.width : 1;
  const down = box.height > 0 ? box.height / frame.height : 1;
  return Math.min(1, across, down);
}
// A pointer on the drawn picture, in the frame's own pixels, which are what the renderer takes.
function designPoint(clientX, clientY, rect, frame) {
  const x = rect.width ? ((clientX - rect.left) * frame.width) / rect.width : 0;
  const y = rect.height ? ((clientY - rect.top) * frame.height) / rect.height : 0;
  return { x: Math.round(x * 10) / 10, y: Math.round(y * 10) / 10 };
}
// The browser protocol's modifier bits: Alt 1, Ctrl 2, Meta 4, Shift 8.
function designModifiers(e) {
  return (e.altKey ? 1 : 0) | (e.ctrlKey ? 2 : 0) | (e.metaKey ? 4 : 0) | (e.shiftKey ? 8 : 0);
}
const DESIGN_BUTTONS = ["left", "middle", "right", "back", "forward"];
// A key on the focused picture, as the renderer's key input: a key that types sends its text, the others go raw.
function designKey(e) {
  const base = { key: e.key, code: e.code, modifiers: designModifiers(e) };
  if (typeof e.keyCode === "number" && e.keyCode > 0 && e.keyCode < 256) base.keyCode = e.keyCode;
  if (e.type === "keyup") return { op: "key", type: "keyUp", ...base };
  const typed = e.key === "Enter" ? "\r" : e.key.length === 1 && !e.ctrlKey && !e.metaKey ? e.key : null;
  return typed === null ? { op: "key", type: "rawKeyDown", ...base } : { op: "key", type: "keyDown", ...base, text: typed };
}
// Whether a keydown on the picture leaves it (FR-019): F6 or Shift+F6 as from the terminal, or Esc twice in a row, which
// goes back to the view's own controls. The first Esc still goes to the board. Returns the step to move focus by (0:
// stay) and when the last Esc was.
function designLeave(e, lastEsc, now) {
  if (e.key === "F6") return { step: e.shiftKey ? -1 : 1, lastEsc: 0 };
  if (e.key !== "Escape" || e.repeat) return { step: 0, lastEsc: 0 };
  if (lastEsc && now - lastEsc <= DESIGN_ESC_TWICE) return { step: -1, lastEsc: 0 };
  return { step: 0, lastEsc: now };
}
// A binary message from hubd: seq, width and height (big endian) ahead of the PNG.
function designPicture(buffer) {
  const head = new DataView(buffer, 0, 12);
  return { seq: head.getUint32(0), width: head.getUint32(4), height: head.getUint32(8), png: new Uint8Array(buffer, 12) };
}
// What a board's or state's name says, for a picker: the file without its extension.
function boardLabel(file) {
  return String(file || "").replace(/\.dc\.html$/, "");
}
function designNow(v) {
  const s = v.state || {};
  if (s.view === "canvas") return `Canvas${s.page ? `, page ${s.page}` : ""}`;
  if (s.board) return `${boardLabel(s.board)}${s.voice ? ` · ${s.voice}` : ""}${s.scheme ? ` · ${s.scheme}` : ""}${s.pen != null ? ` · pen ${s.pen}` : ""}${s.width ? ` · ${s.width}×${s.height}` : ""}`;
  return s.view === "other" ? "Another page" : "Starting";
}

function DesignView({ query }) {
  const name = query.name || "";
  const [v, setV] = useState(null); // hubd's last word on the view: status, project, boards, follow, state…
  const [notes, setNotes] = useState([]);
  const [closed, setClosed] = useState("");
  const [frame, setFrame] = useState(null); // {width, height} of the last picture
  const [actual, setActual] = useState(false); // the 100 % toggle
  const [box, setBox] = useState({ width: 0, height: 0 });
  const [focused, setFocused] = useState(false);
  const [pick, setPick] = useState({ voice: "", scheme: "", pen: "" });
  const canvas = useRef(null);
  const holder = useRef(null);
  const ws = useRef(null);
  const frameRef = useRef(null);
  const send = (m) => { if (ws.current && ws.current.readyState === WebSocket.OPEN) ws.current.send(JSON.stringify(m)); };
  const input = (i) => send({ t: "input", input: i });
  useEffect(() => {
    if (!name) return undefined;
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${scheme}://${location.host}/api/designs/${encodeURIComponent(name)}/view`);
    socket.binaryType = "arraybuffer";
    ws.current = socket;
    let drawing = Promise.resolve();
    socket.onmessage = (e) => {
      if (typeof e.data === "string") {
        let m;
        try { m = JSON.parse(e.data); } catch { return; }
        if (m.t === "view") setV(m);
        else if (m.t === "note" && typeof m.text === "string") setNotes((n) => [...n.slice(-3), m.text]);
        return;
      }
      const p = designPicture(e.data);
      // Pictures are drawn in order, each as a bitmap from PNG bytes: never as an element the page would parse.
      drawing = drawing.then(async () => {
        const bitmap = await createImageBitmap(new Blob([p.png], { type: "image/png" }));
        const c = canvas.current;
        if (!c) return;
        if (c.width !== bitmap.width || c.height !== bitmap.height) { c.width = bitmap.width; c.height = bitmap.height; }
        c.getContext("2d").drawImage(bitmap, 0, 0);
        bitmap.close();
        const f = frameRef.current;
        if (!f || f.width !== p.width || f.height !== p.height) { frameRef.current = { width: p.width, height: p.height }; setFrame(frameRef.current); }
      }).catch(() => {});
    };
    socket.onclose = (e) => setClosed(e.code === 4404 || e.code === 4401 ? e.reason || "There's no design view for this session." : "Disconnected. Open the design view again to reconnect.");
    return () => { socket.onclose = null; socket.close(); ws.current = null; };
  }, [name]);
  // The room the picture has: the holder's width, and the window's height less a margin (the page scrolls to it).
  useEffect(() => {
    const el = holder.current;
    if (!el) return undefined;
    const measure = () => {
      setBox({ width: el.clientWidth, height: Math.max(320, window.innerHeight - 96) });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    window.addEventListener("resize", measure);
    return () => { observer.disconnect(); window.removeEventListener("resize", measure); };
  }, [v !== null]);
  // The pointer, the wheel and touch, in the frame's pixels. Moves wait for the next animation frame, one at a time.
  useEffect(() => {
    const c = canvas.current;
    if (!c) return undefined;
    let moved = null, waiting = false, pressed = false;
    const at = (e) => designPoint(e.clientX, e.clientY, c.getBoundingClientRect(), frameRef.current || { width: c.width, height: c.height });
    const mouse = (type) => (e) => {
      const p = at(e);
      if (type === "mousePressed") c.focus({ preventScroll: true }); // a scroll now would move the picture under the pointer
      const m = { op: "mouse", type, x: p.x, y: p.y, buttons: e.buttons, modifiers: designModifiers(e) };
      if (type !== "mouseMoved") { m.button = DESIGN_BUTTONS[e.button] || "left"; m.clickCount = Math.min(3, Math.max(1, e.detail || 1)); }
      if (type === "mouseMoved") {
        moved = m;
        if (!waiting) { waiting = true; requestAnimationFrame(() => { waiting = false; if (moved) input(moved); moved = null; }); }
        return;
      }
      if (moved) { input(moved); moved = null; }
      e.preventDefault();
      pressed = type === "mousePressed";
      input(m);
    };
    // A button let go outside the picture still ends the press there, or the board would stay held down.
    const outside = (e) => { if (pressed && e.target !== c) { pressed = false; const p = at(e); input({ op: "mouse", type: "mouseReleased", x: p.x, y: p.y, button: DESIGN_BUTTONS[e.button] || "left", buttons: e.buttons, clickCount: 1, modifiers: designModifiers(e) }); } };
    window.addEventListener("mouseup", outside, true);
    const wheel = (e) => {
      e.preventDefault();
      const p = at(e);
      const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1;
      input({ op: "wheel", x: p.x, y: p.y, deltaX: e.deltaX * unit, deltaY: e.deltaY * unit, modifiers: designModifiers(e) });
    };
    const touch = (type) => (e) => {
      e.preventDefault();
      if (type === "touchStart") c.focus({ preventScroll: true });
      const points = [...e.touches].slice(0, 10).map((t) => ({ ...at(t), id: t.identifier % 1000 }));
      // The protocol's end has no points: a finger lifted while others stay is a move of the ones left.
      const kind = (type === "touchEnd" || type === "touchCancel") && points.length ? "touchMove" : type;
      input({ op: "touch", type: kind, points: kind === "touchEnd" || kind === "touchCancel" ? [] : points, modifiers: designModifiers(e) });
    };
    const handlers = [["mousedown", mouse("mousePressed")], ["mouseup", mouse("mouseReleased")], ["mousemove", mouse("mouseMoved")],
      ["wheel", wheel], ["contextmenu", (e) => e.preventDefault()],
      ["touchstart", touch("touchStart")], ["touchmove", touch("touchMove")], ["touchend", touch("touchEnd")], ["touchcancel", touch("touchCancel")]];
    for (const [k, f] of handlers) c.addEventListener(k, f, { passive: false });
    return () => { for (const [k, f] of handlers) c.removeEventListener(k, f); window.removeEventListener("mouseup", outside, true); };
  }, [v !== null]);
  // Keys reach the board only while the picture has focus (FR-019).
  const lastEsc = useRef(0);
  const onKey = (e) => {
    if (e.type === "keydown") {
      const leave = designLeave(e, lastEsc.current, Date.now());
      lastEsc.current = leave.lastEsc;
      if (leave.step) { e.preventDefault(); focusPast(canvas.current, leave.step); return; }
    }
    e.preventDefault();
    input(designKey(e));
  };
  if (!name) return html`<main class="page"><p>No session named.</p></main>`;
  const back = html`<a class="button plain" href=${hash("shells", { tab: "all", name })}>Back to the session</a>`;
  if (!v) return html`<main class="page close"><div class="row">${back}</div><p role="status" class="soft">${closed || "Connecting to the design view…"}</p></main>`;
  const scale = designScale(frame, box, actual);
  const shown = frame ? { width: Math.round(frame.width * scale), height: Math.round(frame.height * scale) } : null;
  const s = v.state || {};
  const opened = (over) => {
    const board = over.board !== undefined ? over.board : s.board;
    if (!board) return;
    const m = { t: "open", board };
    for (const k of ["voice", "scheme", "pen"]) {
      const val = over[k] !== undefined ? over[k] : pick[k] || s[k];
      if (val !== "" && val != null) m[k] = k === "pen" ? Number(val) : val;
    }
    send(m);
  };
  const choose = (k) => (e) => { const val = e.target.value; setPick({ ...pick, [k]: val }); opened({ [k]: val }); };
  const sug = v.suggestion;
  const running = v.status === "running" || v.status === "starting";
  return html`<main class="page close design" aria-labelledby="h-design">
    <div class="row" style="justify-content: space-between">
      <span class="stack" style="gap: 2px"><h1 id="h-design" class="design-title">Design view</h1>
        <span class="mono small soft" style="overflow-wrap: anywhere">${name} · ${v.project}${v.ended ? " · the session has ended" : ""}</span></span>
      <span class="row">${back}</span></div>
    ${closed && html`<div class="notice"><span>${closed}</span></div>`}
    ${v.status === "full" && html`<div class="notice" role="alert"><span>${v.message}</span>
      ${(v.running || []).map((n) => html`<button onClick=${() => send({ t: "stop_other", name: n })}>Stop ${n}</button>`)}</div>`}
    ${v.status === "crashed" && html`<div class="notice" role="alert"><span>The renderer stopped. The session isn't affected.${v.message ? ` ${v.message}` : ""}</span>
      <button class="primary" onClick=${() => send({ t: "restart" })}>Restart</button></div>`}
    ${v.status === "stopped" && html`<div class="notice quiet"><span>The renderer is stopped.</span><button onClick=${() => send({ t: "start" })}>Start it</button></div>`}
    ${v.status === "gone" && html`<div class="notice"><span>${v.message}</span></div>`}
    ${sug && html`<div class="notice quiet" role="status"><span>The session suggests ${boardLabel(sug.board)}${sug.voice ? ` · ${sug.voice}` : ""}${sug.scheme ? ` · ${sug.scheme}` : ""}${sug.pen != null ? ` · pen ${sug.pen}` : ""}${sug.project !== v.project ? ` in ${sug.project}` : ""}.</span>
      <button onClick=${() => send({ t: "take" })}>Show it</button></div>`}
    <div class="design-bar" role="toolbar" aria-label="Design view controls">
      <label class="field"><span>Project</span><select value=${v.project} onChange=${(e) => send({ t: "project", name: e.target.value })}>
        ${(v.projects || []).map((p) => html`<option value=${p}>${p}</option>`)}</select></label>
      <label class="field"><span>Board</span><select value=${s.view === "canvas" ? "" : s.board || ""} onChange=${(e) => (e.target.value ? opened({ board: e.target.value }) : send({ t: "canvas" }))}>
        <option value="">The canvas</option>${(v.boards || []).map((b) => html`<option value=${b}>${boardLabel(b)}</option>`)}</select></label>
      ${[["voice", "Voice", v.voices], ["scheme", "Scheme", v.schemes], ["pen", "Pen", v.pens]].map(([k, label, list]) => html`<label class="field"><span>${label}</span>
        <select disabled=${!s.board} value=${String(pick[k] || (s[k] != null ? s[k] : ""))} onChange=${choose(k)}><option value="">the board's</option>
          ${(list || []).map((x) => html`<option value=${String(x)}>${String(x)}</option>`)}</select></label>`)}
      <label class="row small design-follow"><input type="checkbox" checked=${v.follow} onChange=${(e) => send({ t: "follow", on: e.target.checked })} /> Follow the session</label>
      <span class="row small"><span role="status">Zoom ${Math.round(scale * 100)} %</span>
        <button class="plain" aria-pressed=${actual ? "true" : "false"} onClick=${() => setActual(!actual)}>${actual ? "Fit" : "100 %"}</button></span>
      <button class="plain" onClick=${() => canvas.current && canvas.current.focus()}>Use the picture</button>
      ${running && html`<button class="plain" onClick=${() => send({ t: "restart" })}>Restart renderer</button>`}
    </div>
    <p class="small soft" role="status">${designNow(v)} · ${count(v.viewers, "viewer")}${v.follow ? " · following the session" : " · not following"}${scale < 1 ? " · e-ink is judged at 100 %" : ""}</p>
    ${notes.length > 0 && html`<ul class="small soft">${notes.map((n) => html`<li>${n}</li>`)}</ul>`}
    <div class="design-picture" ref=${holder} style=${actual ? `max-height: ${box.height}px` : ""}>
      <canvas ref=${canvas} tabindex="0" class="design-canvas" style=${shown ? `width: ${shown.width}px; height: ${shown.height}px` : "width: 0; height: 0"}
        aria-label="The boards, live. Keys go to the board while this has focus; Esc twice or F6 leaves it."
        onKeyDown=${onKey} onKeyUp=${onKey} onFocus=${() => setFocused(true)} onBlur=${() => setFocused(false)}></canvas>
      ${!frame && html`<p class="soft" role="status">${running ? "Waiting for the first picture…" : ""}</p>`}
    </div>
    <p class="small soft" role="status">${focused ? "Keys go to the board. Esc twice or F6 leaves the picture." : "Click the picture or use the picture to type into a board."}</p>
  </main>`;
}

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
  if (!o) return "started before origins were kept";
  const f = o.from || {};
  if (o.launch == null && !f.view) return `started directly${o.by ? `, by ${byWords(o.by)}` : ""}`; // the one click or the advanced form: no Launch behind it
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
// after: run once a button, Esc or a move has gone through (the Steward panel reloads its state, so the queued count follows).
function SessionView({ session, mode = "full", asks, here, seen, buttons, queued = 0, after, onView, onEnded, onResume, onGone, onClose, children }) {
  const a = session.agent;
  const name = session.name;
  const full = mode === "full", compact = mode === "compact";
  const act = useAct(after);
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
  const designing = Boolean(a && a.action === "design"); // 011 FR-010: a design session has a design view, at every size
  const [machineOpen, setMachineOpen] = useState(false);
  const chip = a ? chipOf(a.machine, a.ended) : null;
  const embeddedNow = mode === "embedded" || (a && a.view && a.view.mode === "embedded");
  const family = a && FAMILY_WORD[a.family] ? a.family : a ? "unknown" : "shell";
  const head = !compact && html`<header class="svhead ${family}">
    <${PersonaBadge} persona=${personaOf(a)} />
    <span class="stack" style="gap: 2px; flex: 1 1 220px; min-width: 0">
      <h2 id=${hid}>${a ? a.persona_name || a.persona : name}</h2>
      <span class="mono small" style="overflow-wrap: anywhere">${a ? html`${name} · ${shortModel(a.model)}${m && m.branch ? ` · ${m.branch}` : ""}` : session.cwd}</span>
      ${a && html`<span class="small">${originWords(a)}</span>`}</span>
    <span class="badge ${words === "Waiting for you" ? "mark" : a && a.ended ? "dim" : ""}">${words}</span>
    ${chip && html`<${StateChip} machine=${a.machine} ended=${a.ended} />`}
    <span class="row" style="gap: 6px">
      ${a && embeddedNow && html`<button class="plain" disabled=${act.busy} onClick=${() => place("background")}>Send to background</button>`}
      ${designing && html`<a class="button plain" href=${hash("design", { name })}>Design view</a>`}
      ${!full && html`<a class="button plain" href=${hash("shells", { name })}>Open in Sessions</a>`}
      ${full && onClose && html`<button class="plain" onClick=${onClose}>Detach</button>`}
      <button class="plain" disabled=${act.busy} onClick=${stop}>${a ? "Stop…" : "End…"}</button></span></header>`;
  const pills = !compact && (covers.length > 0 || prs.length > 0) && html`<div class="svitems">
    ${covers.length > 0 && html`<span class="row" style="gap: 6px"><span class="eyebrow">Covers</span><${ItemPill} ...${here ? covers.find((c) => `${c.repo}#${c.number}` === here) || covers[0] : covers[0]} /></span>`}
    ${others.length > 0 && html`<nav class="row" style="gap: 6px" aria-label="Also on these items"><span class="eyebrow">Also on these items</span>${others.map((c) => html`<${ItemPill} ...${c} />`)}</nav>`}
    ${prs.length > 0 && html`<span class="row" style="gap: 6px"><span class="eyebrow">Pull requests</span>${prs.map((p) => html`<${ItemPill} kind="pr" repo=${p.repo} number=${p.number} state=${p.state ? String(p.state).toLowerCase() : undefined} />`)}</span>`}</div>`;
  // 012 FR-081: the Workflow row, with the long chip, and the machine panel it opens in place.
  // A session from before workflow instances has none until its machine is first read: opening the panel makes it.
  const wfrow = !compact && a && html`<div class="svwf">
    <span class="eyebrow">Workflow</span>${chip && html`<${StateChip} machine=${a.machine} ended=${a.ended} size="lg" />`}
    <span class="small soft" style="flex: 1 1 200px">${!chip ? "no machine yet: open it to start one from its action" : a.machine.one_state ? `one-state workflow ${a.machine.workflow}, from its action` : `${a.machine.workflow}${a.machine.paused ? " · paused" : ""}`}</span>
    <button type="button" class=${`il-btn${chip && chip.kind === "waits" && !machineOpen ? " wfwaits" : ""}`} aria-expanded=${machineOpen ? "true" : "false"} aria-controls=${`mp-${hid}`}
      onClick=${() => setMachineOpen(!machineOpen)}>${machineOpen ? "Hide the workflow" : "Show the workflow"}</button></div>
    ${machineOpen && html`<div class="svmachine" id=${`mp-${hid}`}><${MachinePanel} name=${name} onMoved=${after} /></div>`}`;
  return html`${dialog}<section class="sv ${mode} ${full ? "termbox" : mode === "embedded" ? "embedded" : "dock-session"}" aria-labelledby=${compact ? undefined : hid} aria-label=${compact ? `Session ${name}` : undefined}>
    ${head}${pills}${wfrow}
    ${!compact && html`<${SessionSpec} session=${session} manifest=${m} error=${error} />`}
    <${Err} text=${act.error} />
    ${mine.length > 0 && html`<div class="${compact ? "dock-asks" : "session-asks"} stack" style="gap: ${compact ? 8 : 10}px">${mine.map((x) => html`<${Ask} key=${x.id} ask=${x} compact=${compact} onDone=${asks.reload} />`)}</div>`}
    ${children}
    ${a && a.waiting && !mine.length && !compact && html`<div role="status" class="waitbar"><span>Waiting for you: answer in the terminal below.</span>
      <button class="plain" onClick=${() => focus.current && focus.current()}>Jump to prompt</button></div>`}
    ${a && a.ended && onResume && html`<div role="status" class="waitbar ended"><span>Claude has ended in this session.</span>
      <button class="plain" disabled=${act.busy} onClick=${onResume}>Resume…</button></div>`}
    <div class=${compact ? "dock-term" : "svterm"} data-theme=${compact ? undefined : "white-night"}><${TerminalView} key=${name} name=${name} quiet=${compact} focusRef=${focus} onGone=${onGone || (() => {})} /></div>
    ${a && html`<div class="svsend ${compact ? "compact" : ""}">
      <div class="row" style="gap: 6px">
        ${offered.map((b) => html`<button class="dock-msg" disabled=${act.busy || !live} title=${b.text.replaceAll("{selection}", thisItem)} onClick=${() => press(b)}>${b.label}</button>`)}
        ${compact && designing && html`<a class="button plain" href=${hash("design", { name })}>Design view</a>`}
        <button class="dock-msg" title="Stops the turn, and anything queued for after it" disabled=${act.busy || !live} onClick=${() => act.run(async () => { await post("agents/interrupt", { name }); setNote("Sent Esc."); })}>Esc</button>
        <span role="status" class="small soft">${queued > 0 ? `${count(queued, "message")} queued until the turn ends, with the prompt empty. If it has ended, clear what's typed there. After Esc in the terminal, press Esc here too.` : note.startsWith("Queued") ? "" : note}</span></div>
      <${MessageField} key=${name} name=${name} where=${where} off=${a.ended ? "Claude has ended in this session: resume it to write to it." : ""} /></div>`}
  </section>`;
}

// --- workflow machines (012) -------------------------------------------------------------------
// The five kinds a state chip draws (FR-080): the edge says which, and so do the words.
function chipKindWords(kind) {
  return { holds: "holds", moving: "moving", waits: "waits for you", up: "sent up", over: "over" }[kind] || "holds";
}

// A session's chip from hubd's summary (agent.machine): the path of states, or a one-state workflow's own name, and its
// kind. What waits for a confirm waits for you; a final state is over, and so is a one-state session once Claude ended.
function chipOf(m, ended) {
  if (!m || !m.state) return null;
  const kind = m.waits ? "waits" : (m.one_state ? ended : m.final) ? "over" : "holds";
  const label = m.one_state ? m.workflow : (m.path && m.path.length ? m.path : [m.state]).join(" › ");
  const words = chipKindWords(kind);
  const sub = m.paused ? `${words} · paused` : words;
  return { kind, label, sub, quiet: Boolean(m.one_state) && kind !== "waits",
    said: `workflow ${m.workflow}, ${m.one_state ? "one state" : `in ${label}`}, ${words}${m.paused ? ", paused" : ""}` };
}

const CHIP_GLYPH = { holds: "M12 8a4 4 0 1 0 0 8 4 4 0 1 0 0-8z", moving: "M4 12h12M12 7l5 5-5 5", waits: "M12 3a9 9 0 1 0 0 18 9 9 0 1 0 0-18zM12 7v5l3 2",
  up: "M12 19V6M6 11l6-6 6 6", over: "M5 12l4 4 10-10" };
// short: only the current state, for a session pill where the path doesn't fit; the path stays in the title (and the
// pill's own label says it all).
function StateChip({ machine, ended, size, short }) {
  const c = chipOf(machine, ended);
  if (!c) return null;
  const label = short && !machine.one_state ? machine.state : c.label;
  const cls = `il-chip${c.kind === "holds" ? "" : ` il-chip--${c.kind}`}${size === "lg" ? " il-chip--lg" : ""}${c.quiet && size !== "lg" ? " wfquiet" : ""}`;
  return html`<span class=${cls} title=${c.said}><svg viewBox="0 0 24 24" aria-hidden="true"><path d=${CHIP_GLYPH[c.kind]} /></svg><span class="sr">Workflow state: </span>${label}<span class="il-chip__sub">· ${c.sub}</span></span>`;
}

// A state's path from the outermost parent, as the machine's states list has them.
function statePath(states, id) {
  const by = Object.fromEntries((states || []).map((s) => [s.id, s]));
  const out = [];
  for (let k = id; k && by[k] && !out.includes(k); k = by[k].parent) out.unshift(k);
  return out;
}

// One `requires` entry as tried now: the text, the values the hub has, and the result in words. A fact the hub has no
// value for is not known yet, never a fail.
function checkWords(c) {
  const seen = (c.terms || []).map((t) => (t.have === null || t.have === undefined ? `${t.fact}: no value yet` : `${t.fact} is ${t.have}`));
  const result = { holds: "holds", fails: "doesn’t hold", unknown: "not known yet" }[c.result] || "not known yet";
  return { text: c.requires, value: seen.join(", ") || "can’t be read", result, mark: c.result === "holds" ? "✓" : c.result === "fails" ? "✗" : "?" };
}

// How an exit decides, in a line: who decides, the judge's question, the facts it needs and how it moves.
function exitWhy(e) {
  const by = { judge: "judged", facts: "facts", counter: "counter", hand: "by hand" }[e.decided_by] || e.decided_by;
  return [by, e.when ? `“${e.when}”` : "", (e.requires || []).length ? `requires ${e.requires.join(", ")}` : "",
    e.approve && e.approve !== "none" ? `approve: ${e.approve}` : "", e.move === "on-request" ? "on request" : "",
    e.enter === "history" ? "back to where it was" : ""].filter(Boolean).join(" · ");
}

// The outline (MachineOutline): states depth-first as the definition lists them, each followed by its children and then
// its own exits, a child's exits before its parent's. tried: the current state's exits from machine.get, for how far each holds.
function outlineRows(states, initial, path, tried) {
  const at = path[path.length - 1];
  const result = new Map((tried || []).map((e) => [`${e.from}:${e.place}`, e.result]));
  const words = { holds: "the checks hold", fails: "doesn’t hold", unknown: "not known yet" };
  const rows = [];
  const visit = (s, depth) => {
    const parent = s.initial !== null && s.initial !== undefined;
    const up = s.parent ? states.find((x) => x.id === s.parent) : null;
    const tags = [];
    if (s.id === at) tags.push("now");
    else if (path.includes(s.id)) tags.push("inside it now");
    if (parent) tags.push("parent");
    if (s.final) tags.push("final");
    if ((up ? up.initial : initial) === s.id) tags.push("starts here");
    const kids = states.filter((x) => x.parent === s.id);
    const sub = parent ? `Its grant and its exits apply in ${kids.map((x) => x.id).join(", ")}.`
      : (s.manages || []).length ? `Runs ${s.manages.map((m) => `${m.persona} (${m.workflow}, ${m.start === "auto" ? "starts on entry" : "on request"})`).join(" and ")}.` : "";
    rows.push({ row: "state", id: s.id, depth, at: s.id === at ? "now" : path.includes(s.id) ? "inside" : "other", tags, sub });
    kids.forEach((k) => visit(k, depth + 1));
    (s.exits || []).forEach((e, i) => {
      const r = path.includes(s.id) ? result.get(`${s.id}:${i + 1}`) : undefined;
      rows.push({ row: "exit", depth: depth + 1, n: parent ? "then, in any of them" : String(i + 1), to: e.to, why: exitWhy(e), holds: r ? words[r] : "" });
    });
  };
  states.filter((s) => !s.parent).forEach((s) => visit(s, 0));
  return rows;
}

// Where a move by hand can go: every state but the one it is in, a parent too (it enters its first state, or where it was).
function moveTargets(states, at) {
  return (states || []).filter((s) => s.id !== at).map((s) => ({ id: s.id, label: statePath(states, s.id).join(" › ") + (s.final ? " (final)" : ""),
    parent: s.initial !== null && s.initial !== undefined, first: s.initial }));
}

// FR-061, FR-081: the statechart, laid out here so the same machine always looks the same. Inside each parent, and at the
// top, states go in columns by how many exits from the first state they are, down a column in the definition's order; a
// parent is a box around its own. An exit is an elbow from one box's side to the other's, labelled with how it decides.
// marks: { at, path, visited, taken, pending } from diagramMarks; all optional.
function diagramLayout(states, initial, marks, down) {
  const D = { w: 150, h: 56, gx: 170, gy: 48, pad: 24, left: 48, head: 60, top: 54, start: 64, margin: 20, label: 18 };
  const m = marks || {};
  const by = Object.fromEntries(states.map((s) => [s.id, s]));
  const isParent = (s) => Boolean(s) && s.initial !== null && s.initial !== undefined;
  const kidsOf = (c) => states.filter((s) => (s.parent || null) === c);
  const pathOf = (id) => { const out = []; for (let k = id; k && by[k] && !out.includes(k); k = by[k].parent) out.unshift(k); return out; };
  const under = (id, c) => { const p = pathOf(id); const i = c === null ? 0 : p.indexOf(c) + 1; return i > 0 || c === null ? p[i] || null : null; };
  const size = {}, rel = {};
  const place = (c) => {
    const kids = kidsOf(c);
    kids.forEach((k) => { if (isParent(k)) place(k.id); else size[k.id] = [Math.max(D.w, k.id.length * 9 + 40), D.h]; });
    const next = new Map(kids.map((k) => [k.id, []]));
    states.forEach((s) => (s.exits || []).forEach((e) => {
      const a = under(s.id, c), b = under(e.to, c);
      if (a && b && a !== b && next.has(a) && !next.get(a).includes(b)) next.get(a).push(b);
    }));
    const rank = {};
    const walk = (first, base) => {
      const queue = [first];
      rank[first] = base;
      while (queue.length) { const x = queue.shift(); for (const y of next.get(x) || []) if (rank[y] === undefined) { rank[y] = rank[x] + 1; queue.push(y); } }
    };
    const first = c === null ? initial : by[c].initial;
    if (next.has(first)) walk(first, 0);
    kids.forEach((k) => { if (rank[k.id] === undefined) walk(k.id, Math.max(-1, ...Object.values(rank)) + 1); });
    const cols = [];
    kids.forEach((k) => { (cols[rank[k.id]] = cols[rank[k.id]] || []).push(k.id); });
    let x = 0, h = 0;
    if (down) {  // ranks as rows, a rank's states side by side
      let y = 0, w = 0;
      cols.filter(Boolean).forEach((row) => {
        let rx = 0, rh = 0;
        row.forEach((id) => { rel[id] = [rx, y]; rx += size[id][0] + D.gx; rh = Math.max(rh, size[id][1]); });
        w = Math.max(w, rx - D.gx); y += rh + D.gy * 1.6;
      });
      x = w + D.gx; h = Math.max(0, y - D.gy * 1.6);
    } else {
      cols.filter(Boolean).forEach((col) => {
        let y = 0, w = 0;
        col.forEach((id) => { rel[id] = [x, y]; y += size[id][1] + D.gy; w = Math.max(w, size[id][0]); });
        h = Math.max(h, y - D.gy); x += w + D.gx;
      });
    }
    const inner = [Math.max(0, x - D.gx), h];
    if (c !== null) size[c] = [Math.max(inner[0] + D.left + D.pad, 290), inner[1] + D.head + D.pad];
    return inner;
  };
  const [cw, ch] = place(null);
  const box = {};
  const put = (c, ox, oy) => kidsOf(c).forEach((k) => {
    const [rx, ry] = rel[k.id];
    box[k.id] = { x: ox + rx, y: oy + ry, w: size[k.id][0], h: size[k.id][1] };
    if (isParent(k)) put(k.id, ox + rx + D.left, oy + ry + D.head);
  });
  put(null, D.margin + D.start, D.top);
  const inside = (a, b) => a.x >= b.x && a.y >= b.y && a.x + a.w <= b.x + b.w && a.y + a.h <= b.y + b.h;
  const visited = new Set(m.visited || []), taken = new Set(m.taken || []), path = m.path || (m.at ? [m.at] : []);
  const ahead = m.pending ? pathOf(m.pending) : [];
  const atOf = (id) => (id === m.at ? "now" : ahead.length && ahead[ahead.length - 1] === id ? "next" : path.includes(id) || visited.has(id) ? "visited" : "other");
  const subOf = (s) => {
    if (isParent(s)) return `parent · ${kidsOf(s.id).length} state${kidsOf(s.id).length === 1 ? "" : "s"}${path.includes(s.id) && s.id !== m.at ? " · inside it now" : ""}`;
    const ms = s.manages || [];
    if (ms.length) { const t = `runs ${ms.map((x) => x.persona).join(", ")}`; return t.length > 20 ? `runs ${ms.length} sessions` : t; }
    return s.final ? "final" : "";
  };
  const shapes = states.filter((s) => box[s.id]).map((s) => {
    const b = box[s.id], at = atOf(s.id);
    const tag = at === "now" ? "NOW" : at === "next" ? "PROPOSED" : "";
    return { id: s.id, ...b, parent: isParent(s), final: Boolean(s.final), at, tag, sub: subOf(s), first: (s.parent ? by[s.parent].initial : initial) === s.id };
  });
  // An entry into each box that holds states: the start dot at the top, a smaller one inside each parent.
  const starts = [null, ...states.filter(isParent).map((s) => s.id)].map((c) => {
    const first = c === null ? initial : by[c].initial;
    const b = box[first];
    if (!b) return null;
    const y = b.y + Math.min(b.h / 2, 28);
    const x0 = c === null ? D.margin + 6 : box[c].x + 16;
    return { x: x0, y, r: c === null ? 6 : 4.5, d: `M${x0 + 6} ${y}H${b.x}` };
  }).filter(Boolean);
  const raw = [];
  const pairs = {};
  states.forEach((s) => (s.exits || []).forEach((e, i) => {
    if (!box[s.id] || !box[e.to]) return;
    const key = [s.id, e.to].sort().join(" ");
    raw.push({ from: s.id, place: e.place || i + 1, e, key, n: (pairs[key] = (pairs[key] || 0) + 1) });
  }));
  const GLYPH = { judge: "≈ ", facts: "= ", counter: "# ", hand: "" };
  const holds = [];
  const edges = raw.map((r) => {
    const { e } = r, A = box[r.from], B = box[e.to], n = pairs[r.key];
    const side = n > 1 ? (r.n - 1 - (n - 1) / 2 < 0 ? -1 : 1) : 0;
    const off = (r.n - 1 - (n - 1) / 2) * 16;
    const words = e.decided_by === "judge" ? e.when || "judged" : e.decided_by === "hand" ? "by hand" : (e.requires || []).join(", ") || e.decided_by;
    const short = words.length > D.label - 2 ? `${words.slice(0, D.label - 3)}…` : words;
    const text = (GLYPH[e.decided_by] === undefined ? "" : GLYPH[e.decided_by]) + short;
    const lw = Math.round(text.length * 7.6 + 14);
    const ys = (b, v) => Math.round(Math.min(b.y + b.h - 10, Math.max(b.y + 10, v)));
    const xs = (b, v) => Math.round(Math.min(b.x + b.w - 10, Math.max(b.x + 10, v)));
    let pts, lx, ly, dir;
    if (r.from === e.to) {
      const x0 = A.x + A.w - 40 + off;
      pts = [[x0, A.y], [x0, A.y - 28], [A.x + A.w + 24, A.y - 28], [A.x + A.w + 24, A.y + 18], [A.x + A.w, A.y + 18]];
      [lx, ly, dir] = [x0 - lw / 2, A.y - 28, [-1, 0]];
    } else if (inside(A, B) || inside(B, A)) {
      const x1 = Math.max(A.x + A.w, B.x + B.w) + 30 + Math.abs(off);
      const sy = ys(A, A.y + A.h / 2 + off), ty = ys(B, B.y + 30 + off);
      pts = [[A.x + A.w, sy], [x1, sy], [x1, ty], [B.x + B.w, ty]];
      [lx, ly, dir] = [x1, (sy + ty) / 2, [-1, 0]];
    } else if (B.x >= A.x + A.w || B.x + B.w <= A.x) {
      const right = B.x >= A.x + A.w;
      const x0 = right ? A.x + A.w : A.x, x1 = right ? B.x : B.x + B.w;
      const sy = ys(A, A.y + Math.min(A.h / 2, 28) + off), ty = ys(B, B.y + Math.min(B.h / 2, 28) + off);
      const mx = Math.round((x0 + x1) / 2 + off);
      pts = sy === ty ? [[x0, sy], [x1, ty]] : [[x0, sy], [mx, sy], [mx, ty], [x1, ty]];
      [lx, ly, dir] = [mx, sy === ty ? sy + side * 13 : (sy + ty) / 2 + side * 13, [right ? 1 : -1, 0]];
    } else {
      const down = B.y >= A.y + A.h;
      const y0 = down ? A.y + A.h : A.y, y1 = down ? B.y : B.y + B.h;
      const sx = xs(A, A.x + A.w / 2 + off * 2), tx = xs(B, B.x + B.w / 2 + off * 2);
      const my = Math.round((y0 + y1) / 2);
      pts = sx === tx ? [[sx, y0], [tx, y1]] : [[sx, y0], [sx, my], [tx, my], [tx, y1]];
      [lx, ly, dir] = [(sx + tx) / 2 + side * (lw / 2 + 6), my, [0, down ? 1 : -1]];
    }
    const end = pts[pts.length - 1];
    if (e.enter === "history" && isParent(by[e.to])) holds.push({ x: end[0] + dir[0] * 16, y: end[1] + dir[1] * 16 });
    const key = `${r.from}:${r.place}`;
    const at = m.pendingExit === key ? "pending" : taken.has(key) ? "taken" : "other";
    return { key, from: r.from, place: r.place, to: e.to, by: e.decided_by, at, text, words, d: `M${pts.map((p) => p.join(" ")).join("L")}`,
      lw, lx: Math.round(lx - lw / 2), ly: Math.round(ly - 11), tx: Math.round(lx), ty: Math.round(ly + 4.5), history: e.enter === "history" };
  });
  const rights = [...Object.values(box).map((b) => b.x + b.w), ...edges.flatMap((g) => g.d.slice(1).split("L").map((p) => Number(p.split(" ")[0]))), ...edges.map((g) => g.lx + g.lw)];
  return { w: Math.max(cw + D.margin + D.start, ...rights) + D.margin, h: D.top + ch + D.margin, states: shapes.filter((s) => !s.parent), parents: shapes.filter((s) => s.parent), edges, starts, holds };
}

// What the diagram marks for a session: the states it went through, the exits the machine's moves took (the innermost
// exit, on the way from where it was, to a state holding where it went; a move by hand takes no exit) and the move that
// waits for a confirm.
function diagramMarks(states, at, path, moves, pending) {
  const pathOf = (id) => statePath(states, id);
  const exitFor = (from, to) => {
    const goal = pathOf(to);
    for (const s of [...pathOf(from)].reverse()) {
      const own = (states.find((x) => x.id === s) || {}).exits || [];
      const i = own.findIndex((e) => goal.includes(e.to));
      if (i >= 0) return `${s}:${own[i].place || i + 1}`;
    }
    return null;
  };
  const went = (moves || []).filter((x) => x.by === "machine" || x.by === "hand" || x.by === "rollback");
  const way = went.slice().sort((a, b) => a.at - b.at);
  const visited = [...new Set(went.flatMap((x) => [x.from, x.to]).filter(Boolean))];
  const taken = [...new Set(went.filter((x) => x.by === "machine").map((x) => exitFor(x.from, x.to)).filter(Boolean))];
  return { at, path: path || [at], visited, taken, pending: pending ? pending.to : null, pendingExit: pending ? exitFor(at, pending.to) : null,
    way: way.length ? [way[0].from, ...way.map((x) => x.to)] : [] };
}

// The statechart itself. Its text alternative is the outline (describedBy); where it is and the way it came are also said
// in words under it. With onPick, a state or an exit's label is a button that selects it.
function MachineDiagram({ states, initial, marks, label, describedBy, sel, onPick }) {
  // Left to right unless that is more than twice as wide as tall: then top to bottom, which fits a column.
  const across = diagramLayout(states, initial, marks);
  const g = across.w > 2.2 * across.h ? diagramLayout(states, initial, marks, true) : across;
  const arrow = `dg-arrow-${describedBy}`;
  const press = (x) => (onPick ? { role: "button", tabindex: "0", onClick: () => onPick(x), onKeyDown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(x); } } } : {});
  const picked = (state, exit) => String(Boolean(sel && sel.state === state && (exit === undefined ? !sel.exit : sel.exit === exit)));
  const m = marks || {};
  const EXIT = { judge: "judged", facts: "by facts", counter: "by a counter", hand: "by hand" };
  return html`<figure class="wf-dgbox stack tight">
    <svg class="wf-dg" viewBox=${`0 0 ${g.w} ${g.h}`} role="group" aria-label=${label} aria-describedby=${describedBy}>
      <defs><marker id=${arrow} viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="11" markerHeight="11" orient="auto-start-reverse"><path class="wf-dg-arrow" d="M0 0L10 5L0 10z" /></marker></defs>
      ${g.parents.map((p) => html`<g class="wf-dg-pa" data-at=${p.at} data-sel=${picked(p.id)} aria-label=${`Parent state ${p.id}${p.at === "visited" && (m.path || []).includes(p.id) ? ", the session is inside it" : ""}`} ...${press({ state: p.id })}>
        <rect x=${p.x} y=${p.y} width=${p.w} height=${p.h} /><text class="wf-dg-name" x=${p.x + 16} y=${p.y + 26}>${p.id}</text><text class="wf-dg-sub" x=${p.x + 16} y=${p.y + 44}>${p.sub}</text></g>`)}
      ${g.starts.map((s) => html`<g aria-hidden="true"><circle class="wf-dg-dot" cx=${s.x} cy=${s.y} r=${s.r} /><path class="wf-dg-start" d=${s.d} marker-end=${`url(#${arrow})`} /></g>`)}
      ${g.edges.map((e) => html`<g class="wf-dg-ed" data-at=${e.at} data-by=${e.by} data-sel=${picked(e.from, e.place)}>
        <path d=${e.d} marker-end=${`url(#${arrow})`} />
        <g class="wf-dg-lab" aria-label=${`Exit ${e.place} of ${e.from} to ${e.to}${e.history ? ", back to where it was" : ""}: ${EXIT[e.by] || e.by}, ${e.words}${e.at === "taken" ? ", taken" : e.at === "pending" ? ", waits for your confirm" : ""}`} ...${press({ state: e.from, exit: e.place })}>
          <title>${e.words}</title><rect x=${e.lx} y=${e.ly} width=${e.lw} height="22" /><text x=${e.tx} y=${e.ty} text-anchor="middle">${e.text}</text></g></g>`)}
      ${g.holds.map((h) => html`<g class="wf-dg-h" aria-hidden="true"><circle cx=${h.x} cy=${h.y} r="11" /><text x=${h.x} y=${h.y + 4.5} text-anchor="middle">H</text></g>`)}
      ${g.states.map((s) => { const tw = s.tag.length * 7.5 + 14; return html`<g class="wf-dg-st" data-at=${s.at} data-sel=${picked(s.id)} aria-label=${`State ${s.id}${s.at === "now" ? ", where it is now" : s.at === "next" ? ", the move waiting for your confirm goes here" : s.at === "visited" ? ", it has been here" : ""}${s.final ? ", final" : ""}`} ...${press({ state: s.id })}>
        <rect x=${s.x} y=${s.y} width=${s.w} height=${s.h} />${s.final && html`<rect class="wf-dg-inner" x=${s.x + 4} y=${s.y + 4} width=${s.w - 8} height=${s.h - 8} />`}
        <text class="wf-dg-name" x=${s.x + s.w / 2} y=${s.y + (s.sub ? 25 : 33)} text-anchor="middle">${s.id}</text>${s.sub && html`<text class="wf-dg-sub" x=${s.x + s.w / 2} y=${s.y + 44} text-anchor="middle">${s.sub}</text>`}
        ${s.tag && html`<g class="wf-dg-tag" aria-hidden="true"><rect x=${s.x + s.w - tw + 6} y=${s.y - 10} width=${tw} height="18" rx="9" /><text x=${s.x + s.w - tw / 2 + 6} y=${s.y + 3} text-anchor="middle">${s.tag}</text></g>`}</g>`; })}
    </svg>
    ${m.at && html`<p class="small">Now in ${(m.path || [m.at]).join(" › ")}.${(m.way || []).length ? ` The way here: ${m.way.join(" → ")}.` : " No moves yet."}${m.pending ? ` A move to ${m.pending} waits for your confirm.` : ""}</p>`}
    <figcaption class="wf-legend"><span><b>≈</b> judged</span><span><b>=</b> facts</span><span><b>#</b> a counter</span><span><b>H</b> back to where it was</span><span>dotted: by hand</span>${m.at && html`<span>heavy box: now</span><span>heavy arrows: the way taken</span><span>heavy dashed arrow: waits for your confirm</span>`}<span>a state’s exits are tried in order; a parent’s exits apply in every state inside it</span></figcaption>
  </figure>`;
}

// One side of a grant change (adds, removes or keeps), as rows: kind, item, the sensitive mark, and whether the instance
// never held it before (what makes the move wait for a confirm).
function grantRows(part, sensitive, never) {
  const KIND = { github: "GitHub", tools: "Tools", hub_tools: "Hub tools", asks_first: "Asks first", access: "Access", permission_mode: "Permission mode",
    all_repos: "All repositories", checkout: "Checkout" };
  const marks = (sensitive && { github: sensitive.github || {}, hub_tools: sensitive.hub_tools || {} }) || { github: {}, hub_tools: {} };
  const rows = [];
  for (const [key, items] of Object.entries(part || {})) {
    for (const x of items || []) {
      const what = key === "all_repos" ? (x ? "every repository" : "named repositories only") : key === "checkout" && x === false ? "none" : String(x);
      const sens = (marks[key] && marks[key][x]) || "";
      rows.push({ key, kind: KIND[key] || key, what, sens, first: Boolean(never && (never[key] || []).includes(x)) });
    }
  }
  return rows;
}

// The machine log, newest first: moves and evaluations together. Evidence and proposals can be an outsider's words, so
// they stay text.
function historyRows(h) {
  const BY = { hand: "moved by hand", machine: "moved", rollback: "rolled back", pause: "paused automatic moves", resume: "resumed automatic moves" };
  const moves = (h && h.moves ? h.moves : []).map((m) => {
    const adds = Object.values(m.change && m.change.adds ? m.change.adds : {}).flat().map(String);
    const removes = Object.values(m.change && m.change.removes ? m.change.removes : {}).flat().map(String);
    const what = m.by === "pause" || m.by === "resume" ? `in ${m.to}` : `${m.from} → ${m.to}`;
    const result = [m.widening ? `widened${m.confirmed_by ? `: confirmed by ${m.confirmed_by}` : ""}` : "", adds.length ? `adds ${adds.join(", ")}` : "",
      removes.length ? `takes away ${removes.join(", ")}` : ""].filter(Boolean).join(" · ");
    return { key: `m${m.seq}`, at: m.at, kind: "move", title: `${BY[m.by] || m.by} · ${what}`, by: m.who || (m.by === "machine" ? "the machine" : "the hub"), result, details: [] };
  });
  const evals = (h && h.evaluations ? h.evaluations : []).map((e) => {
    const checks = Array.isArray(e.checks) ? e.checks.map((c) => (typeof c === "string" ? c : JSON.stringify(c))).join(" · ") : JSON.stringify(e.checks);
    return { key: `e${e.seq}`, at: e.at, kind: "evaluation", title: `tried the exits of ${e.state}`, by: e.judge ? `judge ${e.judge}` : "the hub",
      result: e.failed ? "the judge didn’t answer in form: nothing moved" : e.proposal ? `proposed: ${e.proposal}` : "nothing proposed",
      details: [["Signal", e.signal], ["Evidence", e.evidence || "none"], ["Checks", checks || "none"], ...(e.judge ? [["Judge", `${e.judge}${e.ms != null ? `, ${e.ms} ms` : ""}`]] : [])] };
  });
  return [...moves, ...evals].sort((a, b) => b.at - a.at);
}

// The counters the exits test (rounds, time, tokens), for the states it is in now; rounds for every state it entered.
function counterRows(facts, path) {
  const f = facts || {};
  const rounds = Object.entries(f).filter(([k, v]) => k.startsWith("rounds.") && v > 0).map(([k, v]) => `${k.slice(7)} ${v}`);
  const mins = (s) => (s < 90 ? `${s} s` : s < 5400 ? `${Math.round(s / 60)} min` : `${Math.round(s / 360) / 10} h`);
  const rows = [["Rounds", rounds.join(" · ") || "none"]];
  for (const s of [...path].reverse()) rows.push([`Time in ${s}`, mins(f[`time.${s}`] || 0)], [`Tokens in ${s}`, String(f[`tokens.${s}`] || 0)]);
  return rows;
}

function GrantBlock({ title, rows, sign, id }) {
  return html`<section class="stack tight" aria-labelledby=${id}><h3 class="wfh3" id=${id}>${title}</h3>
    <div class="il-code"><pre>${rows.map((r) => html`<span class=${sign}><span class="sr">${sign === "add" ? "adds " : "takes away "}</span>${r.kind} · ${r.what}${r.first ? " · never held before" : ""}${r.sens ? html` · <strong>Sensitive</strong>: ${r.sens}` : ""}</span>`)}</pre></div></section>`;
}

// FR-024: the confirm a widening move waits for. Confirm and Decline answer it; Not now and Esc close this and leave it waiting.
function WidenConfirm({ name, pending, sensitive, busy, error, onAnswer, onClose }) {
  const ref = useRef();
  useModal(ref);
  const change = pending.change || {};
  const adds = grantRows(change.adds, sensitive, pending.adds);
  const removes = grantRows(change.removes, sensitive);
  const keeps = grantRows(change.keeps, sensitive);
  const sens = adds.filter((r) => r.sens);
  const back = pending.kind === "rollback";
  const why = back ? "You asked to roll back the last move." : pending.kind === "hand" ? "You asked for it by hand." : "The machine proposed it: the first exit that holds.";
  return html`<dialog ref=${ref} class="il-dialog wfconfirm" aria-labelledby="wc-t" aria-describedby="wc-d" onClose=${onClose}>
    <div class="il-dialog__head">
      <span class="il-label">Confirm · this move widens the grant</span>
      <h2 class="il-dialog__title" id="wc-t">${back ? `Roll ${name} back from ${pending.from} to ${pending.to}?` : `Move ${name} from ${pending.from} to ${pending.to}?`}</h2>
      <p class="small soft" id="wc-d">${why} It gives the session something this machine has never held, so it waits for you.</p></div>
    <div class="il-dialog__body">
      ${adds.length ? html`<${GrantBlock} title=${`${pending.to} adds`} rows=${adds} sign="add" id="wc-adds" />` : html`<p class="small">${pending.to} adds nothing over ${pending.from}, but holds something this machine never held: ${grantRows(pending.adds, sensitive).map((r) => `${r.kind} · ${r.what}`).join(", ")}.</p>`}
      ${sens.length > 0 && html`<aside class="il-admonition il-admonition--danger">
        <span class="il-admonition__label"><span class="il-admonition__seal" aria-hidden="true">!</span>Sensitive</span>
        <p class="il-admonition__title">${pending.to} grants ${sens.map((r) => r.what).join(" and ")}</p>
        <p class="small">${sens.map((r) => `${r.what}: ${r.sens}`).join("; ")}. It is marked so you see it; the mark adds no rule.</p>
        <p class="small"><strong>Way out:</strong> Decline, and it stays in ${pending.from} with nothing changed; or Not now, and the move keeps waiting.</p></aside>`}
      ${removes.length > 0 && html`<${GrantBlock} title=${`${pending.to} takes away`} rows=${removes} sign="del" id="wc-rm" />`}
      <p class="small"><span class="eyebrow">Keeps</span> ${keeps.length ? keeps.map((r) => `${r.kind} · ${r.what}`).join(", ") : "nothing of the grant it has now"}</p>
      <div class="wfbox small"><span class="eyebrow">How it resumes</span>
        <p>The hub records the move at once, logged as yours. What the new state takes away goes from the session at once; what it adds comes when the same conversation resumes under a new launch with the new state’s grant, once the session is at its prompt. A stopped session takes it at its next resume. A move that would change its access or checkout goes back, and the log says why.</p></div>
      <${Err} text=${error} /></div>
    <div class="il-dialog__actions">
      <button type="button" class="link wfnotnow" disabled=${busy} onClick=${onClose}>Not now</button>
      <button type="button" class="il-btn" disabled=${busy} onClick=${() => onAnswer(false)}>Decline</button>
      <button type="button" class="il-btn il-btn--primary" disabled=${busy} onClick=${() => onAnswer(true)}>${back ? `Confirm and roll back to ${pending.to}` : `Confirm and move to ${pending.to}`}</button></div>
  </dialog>`;
}

// FR-090, SC-003: what a piece of work cost, as rows: the session and those it manages. Money and tokens the status line
// didn't report are "not reported", never 0.
function costRows(c) {
  const money = (x) => (x === null || x === undefined ? "not reported" : `$${x < 0.01 && x > 0 ? x.toFixed(4) : x.toFixed(2)}`);
  const secs = (ms) => (ms === null || ms === undefined ? "none yet" : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`);
  const span = (s) => (s < 90 ? `${s} s` : s < 5400 ? `${Math.round(s / 60)} min` : `${Math.round(s / 360) / 10} h`);
  const plural = (k, word) => `${k} ${word}${k === 1 ? "" : "s"}`;
  const n = (c.sessions || []).length;
  const lat = c.latency || {};
  const rows = [
    ["Sessions", `${n}${n > 1 ? `, at most ${c.at_once} at once` : ""}`],
    ["Judge calls", `${c.judge_calls}${c.judge_calls ? ` · ${secs(c.judge_ms)} · ${money(c.judge_cost)}` : ""}`],
    ["Tokens", String(c.tokens || 0)],
    ["Cost", money(c.cost)],
    ["Time in states", span(c.seconds || 0)],
    ["Overrides", c.machine_moves ? `${c.overrides} of ${plural(c.machine_moves, "machine move")}` : "no machine moves yet"],
    ["Signal to move", lat.count ? `median ${secs(lat.median_ms)}, at most ${secs(lat.max_ms)}, over ${plural(lat.count, "move")}` : "no machine moves yet"],
  ];
  const fixed = lat.debounce_s === undefined ? ""
    : `of that, fixed: a ${lat.debounce_s} s debounce, up to ${lat.pr_lookup_wait_s} s for a pull request lookup (at most one every ${lat.pr_lookup_every_s} s), and a judge’s limit of ${lat.judge_limit_s} s`;
  const top = (c.sessions || [])[0];
  const states = top ? (top.states || []).map((s) => ({ state: s.parent ? `${s.parent} › ${s.state}` : s.state, rounds: s.rounds, time: span(s.seconds), tokens: String(s.tokens), cost: money(s.cost) })) : [];
  const managed = (c.sessions || []).slice(1).map((s) => `${s.name} (${s.persona || "no persona"}${s.entry ? `, ${s.entry}` : ""}): ${s.tokens} tokens · ${money(s.cost)} · ${plural(s.judge_calls, "judge call")}${s.running ? "" : " · ended"}`);
  return { rows, fixed, states, managed };
}

function CostBox({ id, got }) {
  const c = got.data;
  const r = c ? costRows(c) : null;
  return html`<section class="wfbox stack tight" aria-labelledby=${id}>
    <h3 class="wfh3" id=${id}>Cost</h3>
    ${!c ? html`<p class="small soft">${got.error ? `Can’t read the costs: ${got.error}` : "Reading the costs…"}</p>` : html`
      <p class="small soft">This session and the sessions it manages, over every conversation it has had.</p>
      <dl class="defs">${r.rows.map(([k, x]) => html`<dt>${k}</dt><dd>${x}</dd>`)}</dl>
      ${r.fixed && html`<p class="small soft">Signal to move: ${r.fixed}.</p>`}
      ${r.states.length > 0 && html`<h4 class="eyebrow">Per state</h4><ul class="wfcost stack tight small">${r.states.map((s) => html`<li><b class="mono">${s.state}</b><span class="soft">${s.rounds} round${s.rounds === 1 ? "" : "s"} · ${s.time} · ${s.tokens} tokens · ${s.cost}</span></li>`)}</ul>`}
      ${r.managed.length > 0 && html`<ul class="stack tight small" aria-label="Sessions it manages">${r.managed.map((x) => html`<li>${x}</li>`)}</ul>`}`}
  </section>`;
}

// FR-081, User Story 2: the machine panel, under a session's Workflow row. On a wide screen the diagram comes first, with
// the outline as its text; on a phone the outline stands alone.
function MachinePanel({ name, onMoved }) {
  const path = `machines/${encodeURIComponent(name)}`;
  const phone = usePhone();
  const got = useLoad(() => api(path), [name], 15000);
  const hist = useLoad(() => api(`${path}/history`), [name], 15000);
  const cost = useLoad(() => api(`${path}/costs`), [name], 30000);
  const [asking, setAsking] = useState(null);
  const [to, setTo] = useState("");
  const [enter, setEnter] = useState("first");
  const [note, setNote] = useState("");
  const act = useAct(async () => { await Promise.all([got.reload(), hist.reload()]); if (onMoved) onMoved(); });
  const v = got.data;
  if (!v) return html`<div class="mpanel"><${Err} text=${got.error} />${!got.error && html`<p class="small soft">Reading the machine…</p>`}</div>`;
  const inst = v.instance;
  const at = inst.state;
  const states = v.states || [];
  const here = v.path || [at];
  const one = states.length === 1;
  const step = (move, body = {}) => act.run(async () => {
    const r = await post(`${path}/${move}`, body);
    if (r.needs_confirm) {
      setAsking({ id: r.pending, kind: move === "rollback" ? "rollback" : "hand", from: at, to: r.to, change: r.change, adds: r.adds });
      setNote(`The move to ${r.to} waits for your confirm.`);
    } else if (move === "confirm") {
      setAsking(null);
      setNote(r.moved ? `Moved to ${r.to}.` : `Cancelled: it stays in ${r.state}.`);
    } else if (move === "pause") setNote(r.paused ? "Paused: nothing moves on its own until you resume." : "Resumed: the machine moves on its own again.");
    else if (r.moved) { setNote(move === "rollback" ? `Rolled back to ${r.to}.` : `Moved to ${r.to}.`); setTo(""); }
    return r;
  });
  const waiting = inst.pending;
  const confirmOpen = asking || null;
  const answer = (accept) => step("confirm", { pending: confirmOpen.id, accept });
  const targets = moveTargets(states, at);
  const target = targets.find((t) => t.id === to);
  const exits = v.exits || [];
  const own = exits.filter((e) => e.from === at);
  const inherited = exits.filter((e) => e.from !== at);
  const managed = here.flatMap((s) => ((states.find((x) => x.id === s) || {}).manages || []).map((m) => ({ ...m, under: s })));
  const rows = historyRows(hist.data);
  const RESULT = { holds: "the checks hold", fails: "doesn’t hold", unknown: "not known yet" };
  const exitItem = (e, i, from) => html`<li class="wfexit" data-result=${e.result}>
    <div class="row" style="gap: 6px 10px"><span class="mono">${from ? `then, from ${e.from}` : i + 1}</span><b>→ ${e.to}</b><span class="eyebrow soft">${exitWhy(e).split(" · ")[0]}</span>
      <span class=${`il-chip${waiting && waiting.to === e.to ? " il-chip--waits" : e.result === "holds" ? "" : " il-chip--over"}`}>${RESULT[e.result]}${e.result === "holds" && e.decided_by === "judge" ? " · the judge decides" : ""}</span></div>
    ${e.when && html`<p class="small wfquote">“${e.when}”</p>`}
    ${(e.checks || []).length ? html`<ul class="wfchecks small" aria-label="Checks">${e.checks.map((c) => { const w = checkWords(c); return html`<li><span aria-hidden="true" class="mono">${w.mark}</span><span>${w.text} <span class="soft">· ${w.value} · ${w.result}</span></span></li>`; })}</ul>`
      : html`<p class="small soft">No facts to check${e.decided_by === "hand" ? ": only a move by hand takes it" : ""}.</p>`}</li>`;
  return html`<div class="mpanel stack">
    <div class="row" style="gap: 8px 12px">
      <span class="small soft" style="flex: 1 1 240px">${inst.workflow} · version ${inst.version.slice(0, 8)}${one ? " · one state, from its action" : ` · in ${here.join(" › ")}`}${inst.paused ? " · paused" : ""}</span>
      <a class="il-btn" href=${`#/workflows/${encodeURIComponent(inst.workflow)}`}>Open ${inst.workflow} in the editor</a></div>
    ${v.newer && html`<p class="small notice quiet">${v.newer.kept ? `${inst.workflow} has a newer version; this session stays on its own until you move it by hand.` : v.newer.has_state ? `A newer version of ${inst.workflow} is out: the next move takes it.` : `The newest version of ${inst.workflow} has no state ${at}: this session stays on its version until you move it by hand.`}</p>`}
    <${Err} text=${got.error || hist.error} />
    ${waiting && !confirmOpen && html`<div role="status" class="waitbar"><span>A ${waiting.kind === "rollback" ? "roll-back" : "move"} to ${waiting.to} waits for your confirm: it widens the grant.</span>
      <button type="button" class="il-btn il-btn--primary" onClick=${() => setAsking(waiting)}>See what ${waiting.to} adds…</button></div>`}
    <div class="mpcols">
      <div class="stack">
        <section class="stack tight" aria-labelledby=${`mp-ex-${name}`}>
          <h3 class="wfh3" id=${`mp-ex-${name}`}>Exits from ${at}, in order</h3>
          <p class="small soft">The first exit that holds moves. A fact the hub has no value for yet is not known, not failed.</p>
          ${own.length ? html`<ol class="stack tight">${own.map((e, i) => exitItem(e, i, false))}</ol>` : html`<p class="small">${at} has no exits of its own${one ? ": a one-state workflow ends when the session does" : ""}.</p>`}
          ${inherited.length > 0 && html`<h4 class="eyebrow">Its parents’ exits, after its own</h4><ol class="stack tight">${inherited.map((e, i) => exitItem(e, i, true))}</ol>`}
        </section>
        <section class="stack tight" aria-labelledby=${`mp-sub-${name}`}>
          <h3 class="wfh3" id=${`mp-sub-${name}`}>Running under ${at}</h3>
          ${managed.length > 0 && html`<p class="small">${managed.map((m) => `${m.name}: ${m.persona} on ${m.workflow}, ${m.start === "auto" ? "starts on entry" : "on request"}, under ${m.under}`).join("; ")}.</p>`}
          ${(v.managed || []).length ? html`<ul class="stack tight" aria-label=${`Sessions running under ${at}`}>${v.managed.map((c) => html`<li key=${c.name} class="row" style="gap: 6px 10px">
              <a class="mono" href=${hash("shells", { name: c.name })}>${c.name}</a><span class="small">${c.entry} · ${c.persona}</span>
              <span class="eyebrow soft">${c.state}</span>${c.machine && html`<${StateChip} machine=${c.machine} short />`}
              ${Object.keys((v.returns || {})[c.entry] || {}).length > 0 && html`<span class="small soft">returned ${Object.entries(v.returns[c.entry]).map(([k, x]) => `${k} ${x}`).join(", ")}</span>`}</li>`)}</ul>`
            : html`<p class="small soft">No sessions run under this state.</p>`}</section>
        <section class="stack tight" aria-labelledby=${`mp-ol-${name}`}>
          <h3 class="wfh3" id=${`mp-ol-${name}`}>The whole machine</h3>
          ${!phone && !one && html`<${MachineDiagram} states=${states} initial=${v.initial} marks=${diagramMarks(states, at, here, hist.data && hist.data.moves, waiting)}
            label=${`Statechart of ${inst.workflow}, ${name} is in ${here.join(" › ")}`} describedBy=${`mp-tree-${name}`} />`}
          <ul class="wftree" id=${`mp-tree-${name}`} aria-label=${`States and exits of ${inst.workflow}`}>${outlineRows(states, v.initial, here, exits).map((r) => (r.row === "state"
            ? html`<li data-row="state" data-at=${r.at} style=${`--depth: ${r.depth}`}><span class="row" style="gap: 6px"><b class="mono">${r.id}</b>${r.tags.map((t) => html`<span class=${`il-chip${t === "now" ? " il-chip--waits" : t === "inside it now" ? "" : " il-chip--over"}`}>${t}</span>`)}</span>${r.sub && html`<span class="small soft">${r.sub}</span>`}</li>`
            : html`<li data-row="exit" style=${`--depth: ${r.depth}`} class="small"><span class="mono">${r.n}</span> → <b>${r.to}</b> <span class="soft">${r.why}</span>${r.holds && html` <span>· ${r.holds}</span>`}</li>`))}</ul>
          <details class="wfdef"><summary>Its definition</summary><div class="il-code"><pre>${inst.definition}</pre></div></details>
        </section>
        <section class="stack tight" aria-labelledby=${`mp-h-${name}`}>
          <h3 class="wfh3" id=${`mp-h-${name}`}>History</h3>
          ${rows.length ? html`<ol class="wfhist">${rows.map((h) => html`<li key=${h.key} data-kind=${h.kind}>
            <span class="mono small soft" title=${new Date(h.at * 1000).toLocaleString()}>${whenAgo(h.at)}</span>
            <span class="stack" style="gap: 2px; min-width: 0"><span><b>${h.title}</b> <span class="soft small">by ${h.by}</span></span>${h.result && html`<span class="small">${h.result}</span>`}
              ${h.details.length > 0 && html`<details><summary class="small">Evidence and checks</summary><dl class="defs">${h.details.map(([k, x]) => html`<dt>${k}</dt><dd style="white-space: pre-wrap">${x}</dd>`)}</dl></details>`}</span></li>`)}</ol>`
            : html`<p class="small soft">${hist.loading ? "Reading the log…" : "No moves yet: it has been in its first state since it started."}</p>`}
        </section>
      </div>
      <div class="stack">
        <section class="wfbox stack tight" aria-labelledby=${`mp-c-${name}`}>
          <h3 class="wfh3" id=${`mp-c-${name}`}>Counters</h3>
          <dl class="defs">${counterRows(v.facts, here).map(([k, x]) => html`<dt>${k}</dt><dd>${x}</dd>`)}</dl></section>
        <${CostBox} id=${`mp-cost-${name}`} got=${cost} />
        <section class="wfbox stack tight" aria-labelledby=${`mp-m-${name}`}>
          <h3 class="wfh3" id=${`mp-m-${name}`}>Move by hand</h3>
          <p class="small">To any state, inside a parent or out. Logged as yours. A move that widens the grant asks you to confirm what it adds.</p>
          <label class="stack tight"><span class="eyebrow">Move to</span>
            <select value=${to} onChange=${(e) => { setTo(e.target.value); setEnter("first"); }}>
              <option value="">Choose a state</option>
              ${targets.map((t) => html`<option value=${t.id}>${t.label}</option>`)}</select></label>
          ${target && target.parent && html`<fieldset class="wfenter"><legend class="eyebrow">Enter ${target.id}</legend>
            <label class="row small" style="gap: 8px"><input type="radio" name=${`enter-${name}`} checked=${enter === "first"} onChange=${() => setEnter("first")} /> at its first state (${target.first})</label>
            <label class="row small" style="gap: 8px"><input type="radio" name=${`enter-${name}`} checked=${enter === "history"} onChange=${() => setEnter("history")} /> where it was${inst.history && inst.history[target.id] ? ` (${inst.history[target.id]})` : ": it hasn’t been inside, so its first state"}</label></fieldset>`}
          <div class="row" style="gap: 8px">
            <button type="button" class="il-btn" disabled=${act.busy || !target} onClick=${() => step("move", { to, enter })}>Move by hand</button>
            ${!target && html`<span class="il-btn-reason">Choose a state first.</span>`}</div>
          <div class="row" style="gap: 8px">
            <button type="button" class="il-btn" disabled=${act.busy || !inst.can_roll_back} onClick=${() => step("rollback")}>Roll back the last move</button>
            ${!inst.can_roll_back && html`<span class="il-btn-reason">No move to roll back.</span>`}</div>
          <div class="row" style="gap: 8px">
            <button type="button" class="il-btn" aria-pressed=${inst.paused ? "true" : "false"} disabled=${act.busy} onClick=${() => step("pause", { paused: !inst.paused })}>${inst.paused ? "Resume automatic moves" : "Pause automatic moves"}</button></div>
          <p class="small soft">${inst.paused ? "Paused: nothing moves on its own until you resume. Moves by hand and roll-backs still go." : "While paused, nothing moves on its own; moves by hand and roll-backs still go."}</p>
          <${Err} text=${confirmOpen ? null : act.error} />
          <p role="status" class="small">${note}</p></section>
      </div>
    </div>
    ${confirmOpen && html`<${WidenConfirm} name=${name} pending=${confirmOpen} sensitive=${v.sensitive} busy=${act.busy} error=${act.error}
      onAnswer=${answer} onClose=${() => setAsking(null)} />`}
  </div>`;
}

// --- the workflow editor (012 FR-060 to FR-063, User Story 5) -------------------------------------------------------
// hubd parses, checks, diffs and saves: the page shows what it says. The Text view is the definition; the inspector reads
// the outline hubd made of it and changes nothing, except the order of a state's exits, which hubd writes back as text.
const GRANT_KIND = { tools: "Tools", hub_tools: "Hub tools", asks_first: "Asks first", github: "GitHub", access: "Access",
  permission_mode: "Permission mode", all_repos: "All repositories", checkout: "Checkout" };
const scopeWords = (scope) => (scope === "org" ? "the organisation" : `${scope.replace(/^[^_]+__/, "")} (its override)`);

// The checks as rows: problems first (they stop a save and an approval), then the marks, which only show.
function checkRows(findings) {
  const all = findings || [];
  const problems = all.filter((f) => f.kind === "problem");
  const marks = all.filter((f) => f.kind !== "problem");
  const rows = [...problems.map((f) => ({ kind: "problem", mark: "✗", sr: "Problem: ", title: f.text, where: f.where })),
    ...marks.map((f) => ({ kind: f.kind, mark: "!", sr: "Marked: ", title: f.text, where: f.where }))];
  if (!problems.length) rows.unshift({ kind: "ok", mark: "✓", sr: "", title: "Every state can be reached, every loop ends at a count, every fact is known", where: "" });
  return rows;
}

// Why Approve (or Save) can't be pressed, in words, or null when it can: a problem the checks find stops it.
function approveReason(findings, verb = "Approve") {
  const problems = (findings || []).filter((f) => f.kind === "problem");
  if (!problems.length) return null;
  const first = problems[0];
  return `${verb} waits: the checks find ${problems.length === 1 ? "a problem" : `${problems.length} problems`}. ${first.where ? `${first.where}: ` : ""}${first.text}`;
}

// One row of the outline diff as its two sides. A side is null where the row has no counterpart (added: no before).
function odCells(r) {
  const face = (x, isState) => (x ? { title: x.title, sub: isState ? [...(x.tags || []), x.context && x.context !== "keep" ? `context ${x.context}` : ""].filter(Boolean).join(" · ") : x.sub } : null);
  const isState = r.exit === null || r.exit === undefined;
  const L = face(r.before, isState), R = face(r.after, isState);
  const what = { added: "added", removed: "removed", changed: `changed: ${(r.fields || []).join(", ")}`, moved: `moved from place ${r.was} to ${r.exit}`, same: "" }[r.kind];
  const at = (n) => (isState ? "" : `${n}. `);
  return {
    L: L && { ...L, title: at(r.was) + L.title, mark: r.kind === "same" ? "" : "old" },
    R: R && { ...R, title: at(r.exit) + R.title, mark: r.kind === "same" ? "" : "add" },
    tag: what, isState,
  };
}

// The rows the diff shows, with folds: "only what changes" keeps every state that changes, or any of whose exits does,
// with all its exits, and folds each run of the rest into one row that says how many it hides.
function odRows(rows, only) {
  const list = rows || [];
  const touched = new Set(list.filter((r) => r.kind !== "same").map((r) => r.state));
  const out = [];
  let folded = 0;
  const flush = () => { if (folded) { out.push({ fold: true, text: `⋯ ${folded} unchanged row${folded === 1 ? "" : "s"}` }); folded = 0; } };
  for (const r of list) {
    if (only && !touched.has(r.state)) { folded += 1; continue; }
    flush();
    out.push({ fold: false, row: r, ...odCells(r) });
  }
  flush();
  return out;
}

// The text diff as CodeBlock lines, with what screen readers hear for each sign.
function textDiffLines(lines) {
  return (lines || []).map((l) => ({ cls: l.kind === "add" ? "add" : l.kind === "del" ? "del" : l.kind === "hunk" ? "hunk" : "", sr: l.kind === "add" ? "added: " : l.kind === "del" ? "removed: " : "",
    text: l.text }));
}

// A replay's result in words: what it would have done differently, step by step.
function replayWords(r) {
  if (!r) return null;
  if (r.error) return { title: "The replay couldn't run", body: r.error, rows: [] };
  const n = (r.steps || []).length;
  const title = !n ? "The log has no evaluations for this session" : r.differs ? `It would have moved differently ${r.differs === 1 ? "once" : `${r.differs} times`}` : r.cant_tell ? "No difference the log can show" : "It would have done what the session did";
  const rows = (r.steps || []).filter((s) => s.differs !== false).map((s) => {
    const was = s.kind === "evaluation" ? (s.logged.to ? `moved to ${s.logged.to}` : `stayed in ${s.logged.from}`) : s.kind === "hand" ? `moved by hand to ${s.logged.to}` : `rolled back to ${s.logged.to}`;
    const would = s.replay.result === "moves" ? `would move to ${s.replay.to}` : s.replay.result === "asks" ? `would wait for an approval: ${s.replay.why}` : s.replay.result === "cant_tell" ? `can’t tell: ${s.replay.why}` : `would stay in ${s.replay.from}`;
    return { at: s.at, signal: s.signal || s.kind, text: `${s.kind === "evaluation" ? `In ${s.logged.from}, on ${s.signal}` : "By hand"}: the session ${was}; this ${would}.`, unsure: s.uncertain, cant: s.differs === null };
  });
  const body = [`${count(n, "step")} replayed; it ends in ${r.end}${r.logged_end ? `, the session in ${r.logged_end}` : ""}.`,
    r.cant_tell ? `${count(r.cant_tell, "step")} can’t be told from the log${(r.unknown_facts || []).length ? `: it kept no value for ${r.unknown_facts.join(", ")}` : ""}.` : ""].filter(Boolean).join(" ");
  return { title, body, rows };
}

// The editor's outline: states depth-first in the text's order, each with its own exits under it.
function editorRows(outline) {
  const states = (outline && outline.states) || [];
  const rows = [];
  const visit = (s) => {
    const parent = s.initial !== null && s.initial !== undefined;
    const up = s.parent ? states.find((x) => x.id === s.parent) : null;
    const tags = [parent ? "parent" : "", s.final ? "final" : "", (up ? up.initial : outline.initial) === s.id ? "starts here" : "",
      s.grant.some((g) => g.sensitive && g.from === null) ? "sensitive" : ""].filter(Boolean);
    rows.push({ row: "state", id: s.id, depth: s.depth, tags });
    states.filter((x) => x.parent === s.id).forEach(visit);
    s.exits.forEach((e) => rows.push({ row: "exit", state: s.id, place: e.place, depth: s.depth + 1, to: e.to, why: exitWhy(e), widens: e.widens, n: parent ? `${e.place}, in any of them` : String(e.place) }));
  };
  states.filter((s) => !s.parent).forEach(visit);
  return rows;
}

function Checklist({ findings, id }) {
  return html`<ol class="wfchecklist" aria-labelledby=${id}>${checkRows(findings).map((k) => html`<li data-kind=${k.kind}>
    <span class="wfchecklist-mark" aria-hidden="true">${k.mark}</span>
    <span class="stack" style="gap: 2px"><span><span class="sr">${k.sr}</span><strong>${k.title}</strong></span>${k.where && html`<span class="small mono soft">${k.where}</span>`}</span></li>`)}</ol>`;
}

function OutlineDiff({ rows, only, mode, from, to }) {
  const shown = odRows(rows, only);
  const cell = (c, tag) => (c ? html`<div class="od-cell" data-mark=${c.mark}><span class="sr">${c.mark === "add" ? "After: " : c.mark === "old" ? "Before: " : ""}</span><span class="od-title">${c.title}</span>${c.sub && html`<span class="od-sub">${c.sub}</span>`}${tag && html`<span class="od-tag">${tag}</span>`}</div>`
    : html`<div class="od-cell od-none"><span class="small soft">${"—"}</span></div>`);
  if (!rows) return html`<p class="small">The outline diff needs both versions to parse: see the checks and the text below.</p>`;
  const changed = rows.filter((r) => r.kind !== "same").length;
  return html`<div class="od" data-mode=${mode} role="group" aria-label=${`Outline diff, ${from} to ${to}`}>
    <p class="small soft">${changed ? `${count(changed, "row")} change${changed === 1 ? "s" : ""}, state by state and exit by exit.` : "Nothing changes in the outline."}</p>
    <div class="od-head">${mode === "split" ? html`<span class="eyebrow">Before · ${from}</span><span class="eyebrow">After · ${to}</span>` : html`<span class="eyebrow">${from} → ${to}, in one column</span>`}</div>
    ${shown.map((r) => (r.fold ? html`<div class="od-row od-fold"><span class="small soft">${r.text}</span></div>`
      : html`<div class="od-row" data-kind=${r.row.kind} data-state=${r.isState ? "" : undefined} style=${`--depth: ${r.row.depth}`}>
        ${mode === "split" ? html`${cell(r.L, "")}${cell(r.R, r.tag)}` : html`<div class="od-one">${r.row.kind !== "added" && r.row.kind !== "same" && r.L && cell(r.L, "")}${r.R ? cell(r.R, r.tag) : cell(r.L, r.tag)}</div>`}</div>`))}
  </div>`;
}

function TextDiff({ lines, title, stat }) {
  return html`<div class="il-code wfdiff"><div class="il-code__head"><span class="mono">${title}</span>${stat && html`<span class="small soft">+${stat.added} −${stat.removed}</span>`}</div>
    <pre>${textDiffLines(lines).map((l) => html`<span class=${l.cls}><span class="sr">${l.sr}</span>${l.text}</span>`)}</pre></div>`;
}

function Sensitive({ marks, intro }) {
  const added = (marks || []).filter((m) => m.new !== false);
  if (!added.length) return null;
  return html`<aside class="il-admonition il-admonition--danger">
    <span class="il-admonition__label"><span class="il-admonition__seal" aria-hidden="true">!</span>Sensitive</span>
    <p class="il-admonition__title">${intro} ${count(added.length, "sensitive item")}</p>
    <ul class="stack tight">${added.map((m) => html`<li class="row small" style="gap: 6px 10px"><span class="wfsens">${m.text.split(":")[0]}</span><span>${m.text.split(":").slice(1).join(":").trim()}</span><span class="mono soft">${m.where}</span></li>`)}</ul>
    <p class="small">The mark only shows it: it adds no rule, and saving takes it as written. <strong>Way out:</strong> take it out of the text, or don’t save.</p></aside>`;
}

// The inspector for a state or one of its exits. Read-only: the Text view is the definition.
function Inspector({ outline, sel, onPick, onMove, busy }) {
  const states = (outline && outline.states) || [];
  const s = sel && states.find((x) => x.id === sel.state);
  if (!s) return html`<p class="small soft">Select a state or an exit in the outline to see it here.</p>`;
  if (sel.exit) {
    const e = s.exits.find((x) => x.place === sel.exit);
    if (!e) return html`<p class="small soft">That exit is gone from the text.</p>`;
    const target = states.find((x) => x.id === e.to);
    const field = (k, v) => html`<dt>${k}</dt><dd>${v}</dd>`;
    return html`<div class="stack tight"><span class="eyebrow">Exit</span><h2 class="wfh3" id="wfe-insp">${s.id} → ${e.to}</h2>
      <span class="small soft">Place ${e.place} of ${s.exits.length} in ${s.id}: the first that holds moves.</span>
      <dl class="defs">${field("From", s.path.join(" › "))}${field("To", target ? target.path.join(" › ") : `${e.to} (not a state)`)}
        ${target && target.initial ? field("Enters", e.enter === "history" ? "where it was (history)" : `its first state (${target.initial})`) : null}
        ${field("Decided by", { judge: "a judge’s question", facts: "facts", counter: "a counter", hand: "by hand only" }[e.decided_by] || e.decided_by)}
        ${e.when ? field("When", html`<span class="wfquote">“${e.when}”</span>`) : null}
        ${field("Requires", e.requires.length ? html`<span class="mono">${e.requires.join(" · ")}</span>` : "nothing")}
        ${field("Tried on", e.on.length ? html`<span class="mono">${e.on.join(", ")}</span>` : e.move === "on-request" ? "the session’s request" : "nothing")}
        ${field("Move", e.move === "on-request" ? "on the session’s request" : "on its own")}
        ${field("Approve", e.approve === "none" ? "nobody first" : e.approve)}</dl>
      <p class="small">${e.widens ? `Widens the grant: ${Object.entries(e.adds).map(([k, v]) => `${GRANT_KIND[k] || k} ${v.join(", ")}`).join("; ")}. A session moving here waits for your confirm the first time.` : "Doesn’t widen the grant."}</p>
      <div class="row"><button type="button" class="il-btn" onClick=${() => onPick({ state: s.id })}>Back to ${s.id}</button></div></div>`;
  }
  const groups = {};
  for (const g of s.grant) (groups[g.key] = groups[g.key] || []).push(g);
  const kind = s.initial ? "a parent: its grant and exits hold in every state under it" : s.final ? "final: nothing follows" : "a state a session can be in";
  return html`<div class="stack tight"><span class="eyebrow">State</span><h2 class="wfh3" id="wfe-insp">${s.path.join(" › ")}</h2>
    <span class="small soft">${kind}</span>
    <dl class="defs"><dt>Inside</dt><dd>${s.parent || "top level"}</dd>${s.initial ? html`<dt>First state</dt><dd>${s.initial}</dd>` : null}
      ${s.personas.length ? html`<dt>Personas</dt><dd>${s.personas.join(", ")}</dd>` : null}
      <dt>Context on entry</dt><dd>${s.context === "compact" ? `compact, keeping ${s.focus}` : s.context}</dd></dl>
    ${s.instructions && html`<div class="stack tight"><span class="eyebrow">Instructions on entry</span><p class="small" style="white-space: pre-wrap">${s.instructions}</p></div>`}
    <section class="stack tight" aria-labelledby="wfe-g"><h3 class="wfh3" id="wfe-g">Grant</h3>
      <p class="small soft">With its parents’: what it takes from one says so.</p>
      ${Object.entries(groups).map(([key, items]) => html`<div class="stack" style="gap: 2px"><span class="eyebrow">${GRANT_KIND[key] || key}</span>
        <ul class="wfpick">${items.filter((g) => !(g.set === false)).map((g) => html`<li><span class="small mono">${g.item === false ? "none" : String(g.item)}</span>${g.sensitive && html` <span class="wfsens">sensitive</span>`}<span class="small soft">${g.from ? `from ${g.from}` : "its own"}</span></li>`)}
          ${items.every((g) => g.set === false) && html`<li><span class="small soft">not set: ${items.map((g) => String(g.item)).join(", ")}</span></li>`}</ul></div>`)}</section>
    <section class="stack tight" aria-labelledby="wfe-m"><h3 class="wfh3" id="wfe-m">Sessions it runs</h3>
      ${s.manages.length ? html`<ul class="stack tight">${s.manages.map((m) => html`<li class="wfbox small"><strong>${m.persona}</strong> · workflow <span class="mono">${m.workflow}</span> · ${m.start === "auto" ? "starts on entry" : "on request"}, at most ${m.max}${Object.keys(m.returns).length ? ` · returns ${Object.keys(m.returns).join(", ")}` : ""}</li>`)}</ul>` : html`<p class="small soft">None.</p>`}</section>
    <section class="stack tight" aria-labelledby="wfe-x"><h3 class="wfh3" id="wfe-x">Exits, in order</h3>
      <p class="small soft">The first that holds moves. ↑ and ↓ write the text again through the hub, so its comments go.</p>
      ${s.exits.length ? html`<ol class="wforder">${s.exits.map((e, i) => html`<li><span class="mono">${e.place}</span>
        <button type="button" class="link" onClick=${() => onPick({ state: s.id, exit: e.place })}>→ ${e.to}</button><span class="small soft">${exitWhy(e)}</span>
        <span class="row" style="gap: 4px"><button type="button" class="il-btn" aria-label=${`Move the exit to ${e.to} up`} disabled=${busy || i === 0} onClick=${() => onMove(s.id, e.place, -1)}>↑</button>
          <button type="button" class="il-btn" aria-label=${`Move the exit to ${e.to} down`} disabled=${busy || i === s.exits.length - 1} onClick=${() => onMove(s.id, e.place, 1)}>↓</button></span></li>`)}</ol>`
        : html`<p class="small">${s.final ? "None: it is final." : "None of its own."}</p>`}
      ${s.inherited.map((e) => html`<p class="small"><span class="eyebrow">then, from ${e.from}</span> → ${e.to} · ${exitWhy(e)}</p>`)}</section></div>`;
}

// FR-090: each workflow's averages over the sessions that ran it, beside it in the list.
function costLine(c) {
  if (!c || !c.sessions) return "";
  const pct = c.override_rate === null || c.override_rate === undefined ? "no machine moves yet" : `${Math.round(c.override_rate * 100)}% of the machine’s moves overridden`;
  const lat = c.latency_median_ms === null || c.latency_median_ms === undefined ? "" : ` · signal to move ${c.latency_median_ms < 1000 ? `${c.latency_median_ms} ms` : `${(c.latency_median_ms / 1000).toFixed(1)} s`} (median)`;
  return `${c.sessions} session${c.sessions === 1 ? "" : "s"} · ${c.judge_calls_avg} judge calls each · ${pct}${lat}`;
}

function WorkflowList() {
  const got = useLoad(() => api("hub-workflows"), []);
  const costs = useLoad(() => api("machine-costs"), []);
  const rows = (got.data && got.data.workflows) || [];
  const costOf = Object.fromEntries(((costs.data && costs.data.workflows) || []).map((c) => [c.workflow, c]));
  return html`<main class="page"><div class="stack tight"><${Eyebrow} soft>Hub · workflows<//><h1>Workflows</h1></div>
    <p class="small" style="max-width: 70ch">Each action runs on a workflow. A version you save is never changed after; a session takes the newest at its next move. A repository can have its own override.</p>
    <${Err} text=${got.error} />${!got.data && !got.error && html`<p class="soft">Loading…</p>`}
    <ul class="wflist">${rows.map((w) => html`<li><a href=${`#/workflows/${encodeURIComponent(w.name)}`}><span class="mono"><b>${w.name}</b></span>
      <span class="small soft">${w.states === 1 ? "one state" : `${w.states} states`} · v${w.org}${w.org === 0 ? " (the file)" : ""} for the organisation${w.overrides.length ? ` · overrides: ${w.overrides.map((o) => `${o.repo} v${o.v}`).join(", ")}` : ""}${w.actions.length ? ` · runs ${w.actions.join(", ")}` : ""}</span>
      ${costOf[w.name] && html`<span class="small">${costLine(costOf[w.name])}</span>`}
      ${Object.entries(w.refused).map(([scope, why]) => html`<span class="small">Not in use for ${scopeWords(scope)}: ${why}</span>`)}</a></li>`)}</ul></main>`;
}

function WorkflowsPage({ query }) {
  return query.name ? html`<${WorkflowEditor} key=${`${query.name}:${query.scope || "org"}:${query.proposal || ""}`} name=${query.name} scope=${query.scope || "org"} proposal=${query.proposal} />` : html`<${WorkflowList} />`;
}

function WorkflowEditor({ name, scope, proposal }) {
  const phone = usePhone();
  const [version, setVersion] = useState(null);
  const got = useLoad(() => api(`hub-workflows/${encodeURIComponent(name)}${params({ scope, version: version === null ? "" : String(version), proposal })}`), [name, scope, version]);
  const [draft, setDraft] = useState(null);
  const [checked, setChecked] = useState(null);
  const [view, setView] = useState("outline");
  const [sel, setSel] = useState(null);
  const [session, setSession] = useState("");
  const [replayed, setReplayed] = useState(null);
  const [saving, setSaving] = useState(false);
  const [proposing, setProposing] = useState(false);
  const [asking, setAsking] = useState(false);
  const [note, setNote] = useState("");
  const [said, setSaid] = useState("");
  const [repo, setRepo] = useState("");
  const act = useAct();
  const v = got.data;
  const base = v ? v.text : "";
  const text = draft === null ? base : draft;
  const dirty = draft !== null && draft !== base;
  // A proposal opened from its card: its text is the draft, on the version it starts from.
  useEffect(() => { if (v && v.proposal && draft === null) setDraft(v.proposal.text); }, [v && v.proposal && v.proposal.id]);
  // Checks as you type: hubd parses and checks the text, a moment after the last key.
  useEffect(() => {
    if (!v) return undefined;
    if (!dirty) { setChecked({ findings: v.findings, outline: v.outline }); return undefined; }
    const timer = setTimeout(() => post(`hub-workflows/${encodeURIComponent(name)}/check`, { scope, text }).then(setChecked).catch((e) => setChecked({ findings: [{ kind: "problem", where: "hub", text: e.message }], outline: null })), 400);
    return () => clearTimeout(timer);
  }, [text, v && v.text]);
  if (!v) return html`<main class="page"><${Eyebrow} soft>Hub · workflows<//><h1>${name}</h1><${Err} text=${got.error} />${!got.error && html`<p class="soft">Loading…</p>`}</main>`;
  const findings = (checked && checked.findings) || v.findings;
  const outline = (checked && checked.outline) || (dirty ? null : v.outline);
  const shownV = v.shown.v;
  const next = v.latest + 1;
  const onLatest = v.shown.v === v.latest;
  const saveWhy = !dirty ? "Save waits: nothing is changed yet." : approveReason(findings, "Save") || (!onLatest ? `Save waits: this is v${shownV}; open v${v.latest}, the newest, and change that.` : null);
  const status = `${v.shown.v === 0 && scope === "org" ? "v0, the file under agents/workflows" : `v${v.shown.v}`} for ${scopeWords(scope)}${v.in_use.scope === scope && v.in_use.v === v.shown.v ? " · in use" : ""} · ${count(v.running, "session")} run ${name} now${dirty ? " · edited, not saved" : ""}`;
  const move = (state, place, by) => act.run(async () => { const r = await post(`hub-workflows/${encodeURIComponent(name)}/reorder`, { text, state, place, by }); setDraft(r.text); setSel({ state }); });
  const doReplay = () => act.run(async () => setReplayed(await post(`hub-workflows/${encodeURIComponent(name)}/replay`, { text, session })));
  const save = () => act.run(async () => {
    const r = await post(`hub-workflows/${encodeURIComponent(name)}/save`, { scope, text, base_version: v.latest, note: note || null });
    setSaving(false); setDraft(null); setNote(""); setVersion(null); setSaid(`Saved as v${r.saved.v} for ${scopeWords(scope)} · sessions take it at their next move.`); await got.reload();
  });
  const propose = () => act.run(async () => {
    const r = await post(`hub-workflows/${encodeURIComponent(name)}/propose`, { scope, text, note, session: session || undefined });
    setProposing(false); setNote(""); setSaid(`Sent to Needs you as ${r.decision.id}: approving it there saves it.`);
  });
  const marks = (findings || []).filter((f) => f.kind !== "problem");
  const rows = outline ? editorRows(outline) : [];
  const words = replayWords(replayed);
  const tree = outline ? html`<ul class="wftree wfe-tree" id="wfe-tree" aria-label=${`States and exits of ${name}`}>${rows.map((r) => (r.row === "state"
    ? html`<li data-row="state" style=${`--depth: ${r.depth}`}><button type="button" class="link wfe-pick" aria-pressed=${sel && sel.state === r.id && !sel.exit ? "true" : "false"} onClick=${() => setSel({ state: r.id })}><b class="mono">${r.id}</b></button>${r.tags.map((t) => (t === "sensitive" ? html`<span class="wfsens">sensitive</span>` : html`<span class="il-chip il-chip--over">${t}</span>`))}</li>`
    : html`<li data-row="exit" style=${`--depth: ${r.depth}`} class="small"><button type="button" class="link wfe-pick" aria-pressed=${sel && sel.state === r.state && sel.exit === r.place ? "true" : "false"} onClick=${() => setSel({ state: r.state, exit: r.place })}><span class="mono">${r.n}</span> → <b>${r.to}</b></button> <span class="soft">${r.why}</span>${r.widens && html` · <span>widens</span>`}</li>`))}</ul>` : null;
  const shown = view === "diagram" && phone ? "outline" : view;
  return html`<main class="page wide wfe">
    <header class="wfe-bar">
      <div class="stack tight" style="flex: 1 1 320px"><a class="small" href="#/workflows">Workflows</a><h1 class="mono">${name}</h1><span class="small soft" role="status">${status}</span></div>
      <label class="stack tight small"><span class="eyebrow">Version</span>
        <select value=${String(shownV)} onChange=${(e) => { setVersion(Number(e.target.value)); setDraft(null); }}>${v.versions.map((x) => html`<option value=${String(x.v)}>v${x.v}${x.default ? " · the file" : x.who ? ` · by ${x.who}` : ""}${x.v === v.latest ? " · newest" : ""}</option>`)}
          ${!v.versions.length && html`<option value="0">no override yet: starts from the organisation’s v${v.shown.from}</option>`}</select></label>
      <label class="stack tight small"><span class="eyebrow">Scope</span>
        <select value=${scope} onChange=${(e) => { location.hash = hash(`workflows/${name}`, { scope: e.target.value === "org" ? "" : e.target.value }); }}>${v.scopes.map((s) => html`<option value=${s}>${scopeWords(s)}</option>`)}</select></label>
      <form class="row small" style="gap: 6px; align-items: flex-end" onSubmit=${(e) => { e.preventDefault(); if (repo.trim()) location.hash = hash(`workflows/${name}`, { scope: `GlassineOS__${repo.trim()}` }); }}>
        <label class="stack tight"><span class="eyebrow">Override for a repository</span><input value=${repo} placeholder="boot" onInput=${(e) => setRepo(e.target.value)} /></label>
        <button type="submit" class="il-btn" disabled=${!repo.trim()}>Open</button></form>
    </header>
    <${Err} text=${got.error} />
    <div class="wfe-grid">
      <section class="stack wfe-view" aria-labelledby="wfe-view">
        <h2 class="sr" id="wfe-view">The machine</h2>
        <div class="row" style="justify-content: space-between">
          <div class="seg" role="group" aria-label="View"><button aria-pressed=${shown === "outline" ? "true" : "false"} onClick=${() => setView("outline")}>Outline</button>${!phone && html`<button aria-pressed=${shown === "diagram" ? "true" : "false"} onClick=${() => setView("diagram")}>Diagram</button>`}<button aria-pressed=${shown === "text" ? "true" : "false"} onClick=${() => setView("text")}>Text</button></div>
          ${dirty && html`<button type="button" class="il-btn" onClick=${() => setDraft(null)}>Discard the edits</button>`}</div>
        ${shown === "diagram" && (outline ? html`<${MachineDiagram} states=${outline.states} initial=${outline.initial} label=${`Statechart of ${name}${dirty ? ", edited, not saved" : ""}`}
            describedBy="wfe-tree" sel=${sel} onPick=${setSel} />` : html`<p class="small">The text doesn’t parse, so there is no diagram: see the checks.</p>`)}
        ${shown === "diagram" && outline && html`<details class="wfdef"><summary class="small">The same machine as an outline</summary>${tree}</details>`}
        ${shown === "outline" ? (outline ? tree
          : html`<p class="small">The text doesn’t parse, so there is no outline: see the checks.</p>`)
          : shown === "text" && html`<label class="stack tight"><span class="small soft">${name}.toml · the definition itself: the outline and the inspector read it, and the checks run as you type</span>
            <textarea class="mono wfe-text" spellcheck="false" rows=${phone ? 18 : 30} value=${text} onInput=${(e) => setDraft(e.target.value)}></textarea></label>`}
        ${shown !== "text" && html`<p class="small soft">Select a state or an exit to see it in the inspector. Edit in the Text view.</p>`}
      </section>
      <aside class="wfe-insp wfbox" aria-labelledby="wfe-insp"><${Inspector} outline=${outline} sel=${sel} onPick=${setSel} onMove=${move} busy=${act.busy} /></aside>
      <section class="stack wfe-checks" aria-labelledby="wfe-chk">
        <div class="row"><h2 class="wfh3" id="wfe-chk">Checks</h2><span class="small soft">${approveReason(findings, "Save") ? "a problem stops a save" : marks.length ? `${count(marks.length, "marked item")}: they only show` : "nothing found"}</span></div>
        <${Checklist} findings=${findings} id="wfe-chk" />
        <${Sensitive} marks=${marks.map((m) => ({ ...m, new: true }))} intro="This version grants" />
      </section>
      <section class="stack wfe-replay" aria-labelledby="wfe-rp">
        <h2 class="wfh3" id="wfe-rp">Replay</h2>
        <p class="small soft">Runs this text over a past session’s log: exits decided by facts and counters are evaluated again, a judge’s by the verdict it gave then. What the log didn’t keep can’t be told.</p>
        <div class="row" style="gap: 8px; align-items: flex-end">
          <label class="stack tight small" style="flex: 1 1 240px"><span class="eyebrow">Session</span>
            <select value=${session} onChange=${(e) => { setSession(e.target.value); setReplayed(null); }}><option value="">${v.sessions.length ? "Choose a session" : "No session has run this workflow yet"}</option>
              ${v.sessions.map((s) => html`<option value=${s.session_id}>${s.name} · ${count(s.evaluations, "evaluation")} · ${whenAgo(s.last)}</option>`)}</select></label>
          <button type="button" class="il-btn" disabled=${act.busy || !session || !outline} onClick=${doReplay}>Replay</button>
          ${(!session || !outline) && html`<span class="il-btn-reason">${!outline ? "Replay waits: the text doesn’t parse." : "Choose a session first."}</span>`}</div>
        ${words && html`<div class="wfbox stack tight" role="status"><strong>${words.title}</strong><p class="small">${words.body}</p>
          ${words.rows.length > 0 && html`<ol class="stack tight small">${words.rows.map((r) => html`<li><span class="mono soft">${whenAgo(r.at)}</span> ${r.text}${r.unsure && " (after an earlier difference, so less certain)"}</li>`)}</ol>`}</div>`}
      </section>
    </div>
    <footer class="wfe-foot">
      <button type="button" class="il-btn il-btn--primary" aria-disabled=${saveWhy ? "true" : "false"} aria-describedby="wfe-save-why" onClick=${() => { if (!saveWhy) setSaving(true); }}>Save as v${next}…</button>
      ${saveWhy && html`<span class="il-btn-reason" id="wfe-save-why">${saveWhy}</span>`}
      <button type="button" class="il-btn" disabled=${!dirty} onClick=${() => setProposing(true)}>Propose it…</button>
      ${!dirty && html`<span class="il-btn-reason">Propose waits: nothing is changed yet.</span>`}
      <button type="button" class="il-btn" onClick=${() => setAsking(true)}>Ask for a change…</button>
      <span class="small soft" role="status" style="flex: 1 1 20rem">${said}</span>
      <${Err} text=${saving || proposing ? null : act.error} />
    </footer>
    ${saving && html`<${SaveDialog} name=${name} scope=${scope} next=${next} latest=${v.latest} text=${text} marks=${marks} running=${v.running} note=${note} setNote=${setNote} busy=${act.busy} error=${act.error} onSave=${save} onClose=${() => setSaving(false)} />`}
    ${asking && html`<${AskChangeDialog} name=${name} scope=${scope} onClose=${() => setAsking(false)} />`}
    ${proposing && html`<${ProposeDialog} name=${name} scope=${scope} note=${note} setNote=${setNote} findings=${findings} busy=${act.busy} error=${act.error} onSend=${propose} onClose=${() => setProposing(false)} />`}
  </main>`;
}

function SaveDialog({ name, scope, next, latest, text, marks, running, note, setNote, busy, error, onSave, onClose }) {
  const ref = useRef();
  useModal(ref);
  const diff = useLoad(() => post(`hub-workflows/${encodeURIComponent(name)}/diff`, { scope, from: latest, text }), [text]);
  const changed = diff.data && diff.data.rows ? diff.data.rows.filter((r) => r.kind !== "same") : [];
  return html`<dialog ref=${ref} class="il-dialog wfconfirm" aria-labelledby="wfs-t" onClose=${onClose}>
    <div class="il-dialog__head"><span class="il-label">Save a workflow</span><h2 class="il-dialog__title" id="wfs-t">Save ${name} as v${next} for ${scopeWords(scope)}?</h2></div>
    <div class="il-dialog__body stack">
      <p class="small">${scope === "org" ? `It replaces v${latest} for every repository without its own override.` : `It replaces v${latest} of this repository’s override.`} v${latest} stays as it was: a version never changes.</p>
      ${diff.data ? html`<ul class="stack tight small">${changed.slice(0, 12).map((r) => html`<li>${r.exit ? `${r.state}: exit ${r.exit} → ${r.to}` : r.state} · ${r.kind}${r.fields.length ? `: ${r.fields.join(", ")}` : ""}</li>`)}${changed.length > 12 && html`<li>and ${changed.length - 12} more</li>`}${!changed.length && html`<li>The outline is the same; only the text changes.</li>`}</ul>` : html`<p class="small soft">Reading what changes…</p>`}
      <${Sensitive} marks=${marks.map((m) => ({ ...m, new: true }))} intro="It grants" />
      <p class="small">${count(running, "session")} run ${name} now. Each takes v${next} at its next move, and keeps its own version until then. One in a state v${next} doesn’t have stays on its version until you move it by hand. Saving it is the approval: nothing asks again.</p>
      <label class="stack tight small"><span class="eyebrow">What it’s for (kept with the version)</span><input value=${note} onInput=${(e) => setNote(e.target.value)} /></label>
      <${Err} text=${error || diff.error} /></div>
    <div class="il-dialog__actions"><button type="button" class="il-btn" disabled=${busy} onClick=${onClose}>Keep editing</button>
      <button type="button" class="il-btn il-btn--primary" disabled=${busy} onClick=${onSave}>Save v${next}${marks.length ? `, with ${count(marks.length, "marked item")}` : ""}</button></div>
  </dialog>`;
}

// FR-062, WorkflowAsk: a change asked for in words. It starts a workflow-change session, whose Workflow author drafts it; the hub
// checks and replays each draft and puts the ready one in Needs you. The request goes in as your own notes, not as a brief.
function AskChangeDialog({ name, scope, onClose }) {
  const ref = useRef();
  useModal(ref);
  const [words, setWords] = useState("");
  const act = useAct();
  const ask = () => act.run(async () => {
    const notes = `The workflow: ${name}, for ${scope === "org" ? "the organisation (scope org)" : `${scope.split("__")[1]} (scope ${scope})`}.\n\nThe change I ask for:\n${words.trim()}`;
    const r = await post("agents/run", { action: "workflow-change", notes });
    location.hash = hash("shells", { name: r.name });
  });
  return html`<dialog ref=${ref} class="il-dialog wfconfirm" aria-labelledby="wfa-t" onClose=${onClose}>
    <div class="il-dialog__head"><span class="il-label">Workflows · ${name} · ask for a change</span><h2 class="il-dialog__title" id="wfa-t">Ask the Workflow author</h2></div>
    <div class="il-dialog__body stack">
      <p class="small">A Workflow author drafts the change. The hub checks and replays each draft; one that grants a sensitive item goes to a reviewer first, and after three failed drafts the author asks you. The ready draft comes to Needs you, and nothing is saved until you approve it there.</p>
      <label class="stack tight small"><span class="eyebrow">Your request</span><textarea rows="5" maxlength="3000" value=${words} onInput=${(e) => setWords(e.target.value)}></textarea></label>
      <${Err} text=${act.error} /></div>
    <div class="il-dialog__actions"><button type="button" class="il-btn" disabled=${act.busy} onClick=${onClose}>Back to the editor</button>
      <button type="button" class="il-btn il-btn--primary" disabled=${act.busy || !words.trim()} onClick=${ask}>Ask the Workflow author</button>
      ${!words.trim() && html`<span class="il-btn-reason">Say what you want changed first.</span>`}</div>
  </dialog>`;
}

function ProposeDialog({ name, scope, note, setNote, findings, busy, error, onSend, onClose }) {
  const ref = useRef();
  useModal(ref);
  return html`<dialog ref=${ref} class="il-dialog wfconfirm" aria-labelledby="wfp-t" onClose=${onClose}>
    <div class="il-dialog__head"><span class="il-label">Propose a change</span><h2 class="il-dialog__title" id="wfp-t">Send this version of ${name} to Needs you?</h2></div>
    <div class="il-dialog__body stack">
      <p class="small">It becomes a card with the diff, the checks and the replay. Nothing is saved until it is approved there${approveReason(findings) ? ", and Approve waits while a problem stands" : ""}.</p>
      <label class="stack tight small"><span class="eyebrow">What it changes and why</span><textarea rows="4" value=${note} onInput=${(e) => setNote(e.target.value)}></textarea></label>
      <${Err} text=${error} /></div>
    <div class="il-dialog__actions"><button type="button" class="il-btn" disabled=${busy} onClick=${onClose}>Keep editing</button>
      <button type="button" class="il-btn il-btn--primary" disabled=${busy || !note.trim()} onClick=${onSend}>Send it for ${scopeWords(scope)}</button>
      ${!note.trim() && html`<span class="il-btn-reason">Say what it’s for first.</span>`}</div>
  </dialog>`;
}

// FR-063, DefinitionChange: the card for a proposed version. Approve saves it; it waits, with the reason beside it, while
// the checks find a problem. hubd checks again when it is pressed.
function WorkflowChangeCard({ d, onChanged, where }) {
  const phone = usePhone();
  const [mode, setMode] = useState("split");
  const [only, setOnly] = useState(true);
  const [words, setWords] = useState("");
  const act = useAct(onChanged);
  const s = d.scope;
  const asked = d.state === "requested";
  const why = approveReason(s.findings);
  const send = (verdict, body = {}) => act.run(() => answerAt(d.id, { verdict, ...body }, where));
  const shownMode = phone ? "unified" : mode;
  const rp = replayWords(s.replay);
  const sens = (s.sensitive || []).filter((m) => m.new);
  return html`<article class="stack wfchange" aria-labelledby=${`wc-${d.id}`}>
    <div class="row" style="gap: 8px"><span class="badge">${DECISION_STATE[d.state]}</span><span class="mono small">${d.id}</span><span class="small soft">made ${ago(d.made * 1000)}${d.ended ? `, ended ${ago(d.ended * 1000)}` : ""}</span>
      ${sens.length > 0 && html`<span class="wfsens">${sens.length} sensitive</span>`}</div>
    <h3 class="wfh3" id=${`wc-${d.id}`}>${d.says}</h3>
    <p class="small"><span class="soft">Why, in ${s.proposed_by ? `${s.proposed_by}’s` : "its"} words: </span><span style="overflow-wrap: anywhere">${s.note}</span></p>
    <${Sensitive} marks=${sens} intro="This change grants" />
    <section class="stack tight" aria-label="Before and after">
      <div class="row" style="justify-content: space-between"><h4 class="eyebrow">Before and after</h4>
        ${!phone && html`<div class="seg" role="group" aria-label="Show"><button aria-pressed=${mode === "split" ? "true" : "false"} onClick=${() => setMode("split")}>Side by side</button>
          <button aria-pressed=${shownMode === "unified" ? "true" : "false"} onClick=${() => setMode("unified")}>One column</button></div>`}
        <label class="row small" style="gap: 6px"><input type="checkbox" checked=${only} onChange=${(e) => setOnly(e.target.checked)} />Only what changes</label></div>
      <${OutlineDiff} rows=${s.rows} only=${only} mode=${shownMode} from=${`v${s.base_version}`} to="proposed" /></section>
    <section class="stack tight" aria-label="The change, as written"><h4 class="eyebrow">The change, as written</h4>
      <${TextDiff} lines=${s.text_diff} title=${`${s.workflow} · v${s.base_version} → proposed`} stat=${s.stat} /></section>
    <section class="stack tight" aria-label="The hub’s checks"><h4 class="eyebrow">The hub’s checks</h4><${Checklist} findings=${s.findings} id=${`wc-${d.id}`} />
      <p class="small soft">A problem stops the approval until it is fixed; a sensitive item only marks what you are granting.</p></section>
    ${rp && html`<section class="wfbox stack tight" aria-label="Replay"><strong>Replay: ${rp.title}</strong><p class="small">${rp.body}</p>
      ${rp.rows.length > 0 && html`<ol class="stack tight small">${rp.rows.map((r) => html`<li>${r.text}${r.unsure && " (less certain)"}</li>`)}</ol>`}</section>`}
    ${d.why_ended && html`<p class="small" role="status">Ended: ${d.why_ended}</p>`}
    ${asked && html`<div class="stack tight wfchange-actions">
      <label class="stack tight small">Your words, if you want them on the record<input value=${words} onInput=${(e) => setWords(e.target.value)} /></label>
      ${why && html`<p class="il-btn-reason" id=${`wcw-${d.id}`}>${why}</p>`}
      <div class="row" style="gap: 8px">
        <button type="button" class="il-btn il-btn--primary" aria-disabled=${why ? "true" : "false"} aria-describedby=${why ? `wcw-${d.id}` : undefined} disabled=${act.busy} onClick=${() => { if (!why) send("approve", { words: words || null }); }}>Approve and save${sens.length ? `, with ${sens.length} sensitive` : ""}</button>
        <a class="il-btn" href=${hash(`workflows/${s.workflow}`, { scope: s.scope === "org" ? "" : s.scope, proposal: d.id })}>Open in the editor</a>
        <button type="button" class="il-btn" disabled=${act.busy} onClick=${() => send("deny", { why: words || null, changes: true })}>Ask for changes</button>
        <button type="button" class="il-btn" disabled=${act.busy} onClick=${() => send("deny", { why: words || null })}>Discard</button></div></div>`}
    <${Err} text=${act.error} /></article>`;
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
  if (!hasView(ask.tool, input)) return html`<pre class="ask-code" data-theme="white-night">${JSON.stringify(input, null, 2)}</pre>`;
  const rest = Object.fromEntries(Object.entries(input).filter(([k]) => !TOOL_VIEWS[ask.tool].includes(k)));
  return html`<${AskView} ask=${ask} />${Object.keys(rest).length > 0 && html`<div class="stack" style="gap: 4px"><${Eyebrow} soft>Also set<//><pre class="ask-code" data-theme="white-night">${JSON.stringify(rest, null, 2)}</pre></div>`}`;
}

function AskView({ ask }) {
  const input = ask.input;
  if (ask.tool === MESSAGE_TOOL) return html`<div class="stack" style="gap: 4px"><span class="small">To <span class="mono">${input.name}</span>, as its next turn:</span><pre class="ask-code" data-theme="white-night" style="white-space: pre-wrap">${input.text}</pre></div>`;
  if (ask.tool === "Bash") return html`<pre class="ask-code" data-theme="white-night"><span class="ask-prompt">$ </span>${input.command}</pre>`;
  if (ask.tool === "Edit" || ask.tool === "Write") {
    const lines = ask.tool === "Write" ? askLines(input.content, "+") : [...askLines(input.old_string, "−"), ...askLines(input.new_string, "+")];
    return html`<div class="ask-diff" data-theme="white-night"><span class="ask-path">${input.file_path}</span>
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
const OBJECT_WORDS = { issue: "an issue", pr: "a pull request", run: "a run", repo: "a repository", knowledge: "a question", notes: "the notes" };
const VERB_OBJECT = { issue: "issue", pr: "PR", run: "run", repo: "repo", knowledge: "question", notes: "notes" }; // beside a verb two kinds share, as fix
// Actions about no repository and no item: a research question (008 FR-007), the notes (009 FR-005). hubd's NO_REPO_OBJECTS,
// less the Steward's.
const NO_REPO = ["knowledge", "notes"];
const MAX_COVERS = 6; // hubd's: one item and five more
const coverOf = (c) => ({ kind: c.kind, repo: c.repo, number: c.number });
// A record from before covers were kept names its items by number.
const recordCovers = (r, object) => (r.covers && r.covers.length ? r.covers.map(coverOf)
  : r.number ? [r.number, ...(r.also_numbers || [])].map((n) => ({ kind: object || "issue", repo: r.repo, number: n })) : []);
// 005 FR-011, before planning: hubd says the same and refuses.
function launchRefusal(action, covers) {
  if (!action) return null;
  if (action.object === "repo") return covers.length ? `${action.title} works on a repository, not on an item like ${ref(covers[0])}. Remove the items, or choose another action.` : null;
  if (NO_REPO.includes(action.object)) return covers.length ? `${action.title} works on ${OBJECT_WORDS[action.object]}, not on an item like ${ref(covers[0])}. Remove the items, or choose another action.` : null;
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
        ${d.state === "draft" && html`<label class="boxhit"><input type="checkbox" aria-label=${`Select draft: ${d.title}`} checked=${on} onChange=${() => setPicked({ ...picked, [i]: !on })} /></label>`}
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
    ${editing && html`<p class="small" role="status">Save the draft or cancel first: filing sends the saved text, not what is typed above.</p>`}
    ${item.state === "done" && left > 0 && html`<div class="row">
      <button class=${steward ? "plain" : "primary"} disabled=${act.busy || Boolean(editing) || !chosen.length || unknown.length > 0} onClick=${file}>${chosen.length ? fileLabel : "Choose drafts to file"}</button>
      <button class=${steward ? "primary" : "plain"} disabled=${act.busy || Boolean(editing) || !chosen.length} onClick=${hand}>${steward ? `Send ${chosen.length} to the Steward` : "Send to the Steward instead"}</button>
</div>`}
  </div>`;
}

// 005 FR-016–FR-020 and 003 FR-010: one view per result type, in Launch and on its card in Needs you. The text is the
// session's, which may have read an outsider's: shown as text, never rendered, links printed in full.
const RESULT_TITLE = { comment: "Review to post", labels: "Labels to apply", findings: "Findings", report: "Report", pr: "Pull request", notes: "Note operations" };
const NOTE_OP_WORD = { supersede: "Supersede", merge: "Merge", distil: "Distil", retract: "Retract", answer: "Answer", add: "Add" };
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
      <div class="row"><button class="primary" onClick=${() => launch({ verb: "fix", notes, by: r.session, from: { view: where } })}>Start a fix session</button>${setAside}</div>`;
  } else if (r.type === "report") {
    body = html`${p.question && html`<span class="eyebrow">Question</span>${plainText(p.question)}`}<span class="eyebrow">Answer</span>${plainText(p.answer)}
      ${(p.unsettled || []).length > 0 && html`<span class="eyebrow">Couldn't settle</span><ul>${p.unsettled.map((t) => html`<li>${plainText(t)}</li>`)}</ul>`}
      ${(p.sources || []).length > 0 && html`<span class="eyebrow">Sources</span><ul class="stack" style="gap: 4px">${p.sources.map((s) => html`<li>${plainText(`${s.link} — ${s.why}`)}</li>`)}</ul>`}
      ${(p.followups || []).length > 0 && html`<span class="eyebrow">Follow-ups</span><ul>${p.followups.map((t) => html`<li>${plainText(t)}</li>`)}</ul>`}
      ${r.kept ? html`<p class="small" role="status">Saved to Knowledge.</p>` : waits && html`<div class="row"><button class="primary" disabled=${act.busy} onClick=${() => answer("keep")}>Save to Knowledge</button>${setAside}</div>`}`;
  } else if (r.type === "notes") {
    // 009 FR-006: each op with the exact command hubd built and will run; apply one or all. None deletes a note.
    // An op whose outcome is unknown (hubd stopped while it ran, or the tool didn't answer) never runs again until you say
    // whether it's in the notes.
    const ops = p.ops || [];
    const waiting = (o) => o.state === "pending" || o.state === "failed";
    const left = ops.filter(waiting).length;
    body = html`${p.summary && plainText(p.summary)}
      <ol class="stack" style="gap: 10px">${ops.map((o, n) => html`<li class="stack tight">
        <div class="row" style="gap: 8px"><b>${NOTE_OP_WORD[o.op] || o.op}</b><span class="mono small">${o.topic}</span>${(o.ids || []).length > 0 && html`<span class="mono small soft">${o.ids.join(", ")}</span>`}
          <span class="badge ${o.state === "failed" || o.state === "unknown" ? "bad" : o.state === "applied" ? "dim" : ""}">${o.state === "unknown" ? "may be in already" : o.state}</span></div>
        ${o.words && plainText(o.words)}${o.why && html`<span class="small soft">Why: ${o.why}</span>`}
        <code class="small mono" style="white-space: pre-wrap; overflow-wrap: anywhere">${o.command}</code>
        ${o.said && html`<span class="small" role=${o.state === "failed" || o.state === "unknown" ? "alert" : null} style="overflow-wrap: anywhere">${o.state === "failed" ? "The notes tool said: " : ""}${o.said}</span>`}
        ${r.state === "pending" && o.state === "unknown" && html`<div class="row"><span class="small">Search ${o.topic} in Notes: is it there?</span>
          <button class="plain" disabled=${act.busy} onClick=${() => answer("resolve", { index: n, found: true })}>It's in the notes</button>
          <button class="plain" disabled=${act.busy} onClick=${() => answer("resolve", { index: n, found: false })}>It isn't</button></div>`}
        ${r.state === "pending" && waiting(o) && ops.length > 1 && html`<button class="plain" style="align-self: flex-start" disabled=${act.busy} onClick=${() => answer("apply", { indexes: [n] })}>Apply this one</button>`}</li>`)}</ol>
      <p class="small soft">Nothing is deleted: what's replaced, retracted or answered stays in the topic's Log.</p>
      ${r.state === "pending" && left > 0 && html`<div class="row"><button class="primary" disabled=${act.busy} onClick=${() => answer("apply")}>${left === ops.length ? "Apply all" : `Apply the ${count(left, "other")}`}</button>${setAside}</div>`}`;
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
  const initial = actions.find((a) => a.id === seed.action)
    || (seed.verb && (actions.find((a) => a.verb === seed.verb && seed.covers && seed.covers[0] && a.object === seed.covers[0].kind) || actions.find((a) => a.verb === seed.verb)))
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
  const noRepo = NO_REPO.includes(action.object);
  const onItems = action.object !== "repo" && !noRepo;
  const chosenRepo = noRepo ? null : action.repo || repo;
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
      <div role="radiogroup" aria-labelledby="lb-action" class="row" style="gap: 6px">${verbs.map((a) => html`<button role="radio" class="pill" aria-checked=${a.id === action.id ? "true" : "false"} title=${a.title} onClick=${() => setActionId(a.id)}>${a.verb}${verbs.some((b) => b !== a && b.verb === a.verb) ? html` <span class="soft">${VERB_OBJECT[a.object]}</span>` : ""}</button>`)}</div>
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
        ${action.repository ? html`<span class="small soft">The session's checkout is a new branch of GlassineOS/${action.repository}, whichever repository the items are in; they are listed as covered.</span>`
          : covers.length > 1 && html`<span class="small soft">The session's checkout is in ${covers[0].repo}, the first item's repository; the others are listed as covered.</span>`}</div>`
      : noRepo ? html`<div class="small"><${Eyebrow}>About<//> ${action.object === "knowledge" ? "a question: no repository and no checkout. The notes below are the question and its scope."
        : "the shared notes: no repository and no checkout. The notes below name the topic."}</div>`
      : action.repo ? html`<div class="small"><${Eyebrow}>In<//> <span class="mono">GlassineOS/${action.repo}</span> · org board</div>`
      : html`<${RepoPicker} value=${repo} onChange=${setRepo} groups=${groups} label="Repository" />`}
    ${launchRefusal(action, covers) && html`<p class="small" role="alert">${refusal}</p>`}
    ${action.asks_paths && html`<label class="nw-field">Scope <span class="nw-sub">optional · paths in the repository</span>
      <input class="mono" value=${paths} placeholder="the whole repository" onInput=${(e) => setPaths(e.target.value)} /></label>`}
    ${action.asks_describe && html`<label class="nw-field">${text.label || "What to plan"}
      <textarea rows="3" placeholder=${text.hold || ""} value=${describe} onInput=${(e) => setDescribe(e.target.value)} /></label>`}
    ${suggester && html`<p class="small"><span class="nw-tag">${suggester === "the Steward" ? "STEWARD" : "SUGGESTED"}</span> ${suggester} wrote the notes below, and they reach the planner and the session as yours once you press Plan: read them first; edit freely.</p>`}
    <${SteerFields} kind=${action.object} notes=${notes} pins=${pins} onNotes=${setNotes} onPins=${setPins} rows=${suggester ? 8 : 2} />
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
      <button class="primary" disabled=${act.busy || Boolean(refusal) || (action.object === "repo" && !chosenRepo) || (action.asks_describe && !describe.trim())}
        title=${refusal || (action.object === "repo" && !chosenRepo ? "Choose a repository first" : "")} onClick=${plan}>${action.plan === false ? "Next: nothing to plan" : "Plan"}</button>
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

// What this Launch's session handed in, or the pull request it opened.
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

// One Launch, from brief to result. The record (hubd's) is the stage: the page only holds the brief until Plan.
function LaunchModal({ open, work, asks, reload, onClose, onBehind }) {
  const dialog = useRef();
  const [id, setId] = useState(open.id || null);
  const [editing, setEditing] = useState(false);
  const [fresh, setFresh] = useState(null); // a record Plan just made, until the list has it: the brief must not come back with Plan enabled
  const [note, setNote] = useState(null);
  const { list: actions, error: actionsError } = useLaunchActions(work.templates);
  const { data: overview } = useLoad(() => api("overview"), []);
  const act = useAct(reload);
  const [confirm, confirmDialog] = useConfirm();
  useModal(dialog);
  const live = id ? work.items.find((i) => i.id === id) || null : null;
  const action = actions && live ? actions.find((a) => a.id === live.action) : null;
  useEffect(() => { if (live && fresh) setFresh(null); }, [Boolean(live)]);
  const starting = !live && id !== null && id === fresh;
  const stage = starting ? "planning" : !live || live.state === "offered" || editing ? "brief" : live.stage || "brief";
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
            onCancel=${editing ? () => setEditing(false) : null} onPlanned=${(w) => { setFresh(w.id); setId(w.id); setEditing(false); return reload(); }} />`
        : shown === "planning" ? html`<div class="nw-body" role="status"><span class="row" style="font-weight: 600; font-size: 18px"><${StateIcon} kind="run" />The planner is reading</span>
            <span class="mono soft" style="font-size: 12.5px">claude -p · ${live ? `${NW_MODEL[live.planner_model || PLANNER_DEFAULT]} · ` : ""}read-only hub tools · up to a few minutes</span>
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
    ${d.asked_by && !d.kind.startsWith("machine.") && html`<p class="small soft">Asked for by ${d.asked_by}, in its own words, which aren't yours: <span style="overflow-wrap: anywhere">${d.why}</span></p>`}
    ${d.kind.startsWith("machine.") && html`<p class="small" style="overflow-wrap: anywhere">From the hub: ${d.why}</p>`}
    ${d.scope && d.scope.type === "design" && html`<p class="row"><a class="il-btn" href=${hash("design", { name: d.scope.design })}>Look at the design</a></p>`}
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
    if (item.kind === "decision") return html`<div class="ask calm ${settled ? "done" : ""}"><div class="ask-head"><span class="ask-kind">${d.kind === "go" ? (d.scope.actions.includes("eye-test") ? "GO · EYE TEST" : "GO") : d.kind === "machine.widen" ? "WORKFLOW MOVE" : d.kind === "machine.approve" ? "WORKFLOW APPROVAL" : d.kind === "workflow.change" ? "WORKFLOW CHANGE" : "MERGE"}</span>
      <span class="small mono">${d.asked_by || (d.scope && d.scope.proposed_by) || "you"}</span></div><div class="ask-body">${d.kind === "workflow.change"
        ? html`<${WorkflowChangeCard} key=${`${d.id}-${d.state}`} d=${d} onChanged=${reload} where=${where} />`
        : html`<${DecisionRow} key=${`${d.id}-${d.state}`} d=${d} onChanged=${reload} where=${where} />`}</div></div>`;
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
  useModal(ref);
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
  useModal(ref);
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
  const live = useSessions();
  // Asked again when a session starts or ends anywhere: a conversation running again leaves this list (hubd decides which).
  const running = (live.data || []).filter((s) => s.agent && !s.agent.ended).map((s) => s.name).sort().join(" ");
  // 004 FR-016: hubd narrows by persona, repository and outcome.
  const { data, error, reload } = useLoad(() => post("agents/past", { persona: persona || undefined, repo: repo || undefined, outcome: filter === "all" ? undefined : filter }), [persona, repo, filter, running]);
  const everything = useLoad(() => post("agents/past"), []);
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
  // 004 FR-018: one already running again says so, instead of offering to resume it twice. hubd says which, by the
  // conversation's own id: a later session can reuse the name, and that one is a different conversation.
  const runningAgain = (r) => r.running_again;
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
          : r.transcript ? html`<button class="primary" disabled=${act.busy} onClick=${() => resume(r)}>${resuming === r.id ? (r.worktree === "removed" ? "Restoring…" : "Resuming…") : r.worktree === "removed" ? "Restore & resume" : "Resume"}</button>`
          : html`<span class="small soft">Its transcript is gone.</span>`}
        ${r.transcript && html`<button disabled=${act.busy} onClick=${() => setReading(r)}>Transcript</button>`}</div></div>`)}</div>
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
      <label class="boxhit"><input type="checkbox" aria-label=${`Select ${r.id}`} disabled=${r.state !== "safe"} checked=${!!picked[r.id] && r.state === "safe"} onChange=${() => setPicked({ ...picked, [r.id]: !picked[r.id] })} /></label>
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
const needsState = (c) => (c.blocking > 0 ? "blocking" : c.pending > 0 ? "pending" : "none");
function NeedsButton({ asks, before }) {
  const c = asks.interactions.counts;
  const state = needsState(c);
  return html`<button class="needs-open ${state === "none" ? "plain" : ""}" data-state=${state} data-waits=${state === "blocking" ? "" : undefined}
    aria-label=${needsLabel(asks)} onClick=${() => { if (before) before(); needsYou(); }}>Needs you <span class="ask-tally">${c.pending}</span></button>`;
}

// 001 FR-007: at phone width the header is "New" and "Menu". Menu carries the Needs you count, in the same three states
// as the Needs you button, so what waits for you still shows on every view.
function MenuButton({ asks, onOpen }) {
  const c = asks.interactions.counts;
  const state = needsState(c);
  const waits = c.pending ? `, ${count(c.pending, "thing")} waiting for you${c.blocking ? `, ${c.blocking} blocking a session` : ""}` : "";
  return html`<button class="needs-open menu-open ${state === "none" ? "plain" : ""}" data-state=${state} data-waits=${state === "blocking" ? "" : undefined}
    aria-haspopup="dialog" aria-label=${`Menu${waits}`} onClick=${onOpen}>Menu${c.pending > 0 && html` <span class="ask-tally" aria-hidden="true">${c.pending}</span>`}</button>`;
}

// The Menu sheet: the navigation, Needs you and the user line (001 FR-007), a full sheet that traps focus and closes on
// Esc (001 FR-016).
function MenuSheet({ here, asks, host, onOut, onClose }) {
  const ref = useRef(null);
  useModal(ref);
  const close = () => { if (ref.current && ref.current.open) ref.current.close(); };
  return html`<dialog ref=${ref} class="sheet menu" aria-labelledby="menu-h" onClose=${onClose}>
    <div class="needs-head"><h2 id="menu-h">Menu</h2><button class="square" aria-label="Close the menu" onClick=${close}>×</button></div>
    <div class="menu-body">
      <nav aria-label="Primary"><ul>${NAV.map(([key, label]) => html`<li><a href=${key === "shells" ? hash("shells", { tab: "all" }) : `#/${key}`}
        aria-current=${here === key ? "page" : null} onClick=${close}>${label}</a></li>`)}</ul></nav>
      <${NeedsButton} asks=${asks} before=${close} />
      <div class="menu-user stack tight">
        ${!host.gh && html`<span class="badge bad">no gh on the host</span>`}
        ${!host.tmux && html`<span class="badge bad">no tmux on the host</span>`}
        <${UsageMeter} />
        <span class="small whoami"><span class="mono">${host.user}</span>${host.hubd && html` · <span class="soft">hubd</span> <span class="mono soft">${host.hubd}</span>`}</span>
        <button class="plain" style="align-self: flex-start" onClick=${async () => { await post("logout"); onOut(); }}>Sign out</button></div></div></dialog>`;
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

const SESSIONS_EVERY = 4000; // ms

// 004 FR-012: Running, in four groups by where a session is drawn and whether Claude still runs in it.
const RUN_GROUPS = [["embedded", "Embedded in a view"], ["background", "In the background"], ["finished", "Finished, tmux still open"], ["plain", "Plain shells"]];
const runGroup = (s) => (!s.agent ? "plain" : s.agent.ended ? "finished" : s.agent.view && s.agent.view.mode === "embedded" ? "embedded" : "background");
const readBadgesOnly = () => { try { return localStorage.getItem("sessions-badges") === "1"; } catch { return false; } };

function Shells({ query, asks }) {
  const [kept, setKept] = useState(null);
  // Sessions are started from other pages and by the Steward, so this list is the one that polls quickly.
  const { data, error, reload } = useLoad(() => api("shells"), [], SESSIONS_EVERY);
  const stopped = useLoad(() => api("agents/stopped").catch(() => []), [], SESSIONS_EVERY);
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
    const chip = a ? chipOf(a.machine, a.ended) : null;
    const label = `${s.name}: ${a ? `${a.persona_name || a.persona}, ` : ""}${words}${waiting ? `, ${waiting} waiting` : ""}${chip ? `, ${chip.said}` : ""}`;
    if (badgesOnly) {
      return html`<button class="sess-badge" aria-pressed=${open === s.name ? "true" : "false"} aria-label=${label} title=${label} onClick=${() => setOpen(s.name)}>
        <${PersonaBadge} persona=${personaOf(a)} hidden />${waiting > 0 && html`<span class="dock-count">${waiting}</span>`}</button>`;
    }
    return html`<button class="sess-item" aria-pressed=${open === s.name ? "true" : "false"} onClick=${() => setOpen(s.name)}>
      <span class="h"><span class="row" style="gap: 8px; flex-wrap: nowrap; min-width: 0"><${PersonaBadge} persona=${personaOf(a)} /><b>${s.name}</b></span>
        <span class="badge ${words === "Waiting for you" ? "mark" : a && a.ended ? "dim" : ""}">${words}</span></span>
      ${chip && html`<span><${StateChip} machine=${a.machine} ended=${a.ended} /></span>`}
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
  <svg width="32" height="32" viewBox="0 0 32 32" aria-hidden="true"><rect x="3" y="3" width="18" height="22" rx="2" fill="none" stroke="currentColor" stroke-width="1.5" /><rect x="11" y="7" width="18" height="22" rx="2" fill="var(--highlight)" stroke="var(--pen)" stroke-width="1.5" /></svg>
  <span><span class="eyebrow">GlassineOS Hub</span><small>GlassineOS/hub</small></span></a>`;

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

// --- the device lock, on Overview (007 FR-003) ---------------------------------------------------
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
      ${r.next && html`<span class="badge">Next</span>`}
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
// 009 FR-003: the trust labels, in words; a state the page doesn't know reads as no status, never as a fact.
const TRUST = {
  current: ["CURRENT", "", "Holds now, with evidence."],
  open: ["OPEN QUESTION", "", "Not settled yet."],
  history: ["HISTORY", "dim", "Was so once; the log keeps it."],
  retracted: ["RETRACTED", "bad", "Shown wrong by a later note."],
  "archive, unreviewed": ["ARCHIVE·UNREVIEWED", "dim", "From an old source nobody has checked."],
  "no state given": ["NO STATUS", "bad", "The note says nothing about itself."],
};
const trustOf = (state) => TRUST[state] || TRUST["no state given"];
const NOTES_PAGE = 20; // rows at first, then 20 more at a time (009 FR-002)
const NOTES_MOST = 100; // hubd's limit
const NOTES_LONG = 220; // characters before a row folds
// The command that lists everything, for the limit box: the words as the tool will see them, each quoted.
const shellWord = (w) => (/^[A-Za-z0-9_./:+-]+$/.test(w) ? w : `'${w.replace(/'/g, "'\\''")}'`);
const notesCommand = (words, total) => `notes find --limit ${total} -- ${words.trim().split(/\s+/).map(shellWord).join(" ")}`;
// A note has no title of its own: its first sentence stands in, and the rest folds.
const noteTitle = (text) => { const m = /^(.{1,120}?[.!?])(\s|$)/.exec(text); return m ? m[1] : text.slice(0, 120); };

function TrustLegend() {
  return html`<dl class="defs" aria-label="Trust labels">${Object.values(TRUST).map(([word, cls, means]) => html`<dt><span class="badge ${cls}">${word}</span></dt><dd class="small">${means}</dd>`)}</dl>`;
}

function NoteRow({ r }) {
  const [open, setOpen] = useState(false);
  const [word, cls] = trustOf(r.state);
  const title = noteTitle(r.text);
  const long = r.text.length > NOTES_LONG || r.text.trim().length > title.length + 40;
  return html`<article class="stack" style="gap: 4px; padding: 10px 0; border-bottom: 1px solid var(--rule)" aria-label=${`${word}: ${r.where}`}>
    <div class="row" style="gap: 8px"><span class="badge ${cls}">${word}</span><b style="flex: 1 1 260px; min-width: 0; overflow-wrap: anywhere">${title}</b></div>
    <div class="row small soft" style="gap: 4px 12px"><span class="mono" style="overflow-wrap: anywhere">${r.topic || r.where}</span>
      ${r.topic && r.where !== r.topic && html`<span class="mono">${r.where.slice(r.topic.length + 1) ? `line ${r.where.slice(r.topic.length + 1)}` : ""}</span>`}
      ${r.label && html`<span class="mono" style="overflow-wrap: anywhere">${r.label}</span>`}${r.date && html`<span>${r.date}</span>`}</div>
    ${long ? html`${open && html`<p style="overflow-wrap: anywhere; white-space: pre-wrap">${r.text}</p>`}
      <button class="link" style="align-self: flex-start" aria-expanded=${open ? "true" : "false"} onClick=${() => setOpen(!open)}>${open ? "Show less" : "Show the whole note"}</button>`
      : r.text.trim() !== title && html`<p style="overflow-wrap: anywhere">${r.text}</p>`}</article>`;
}

// 009 FR-005: totals per label and per topic, and the two upkeep actions, for all notes or one topic.
function KeepNotesUseful({ onClose }) {
  const ref = useRef();
  useModal(ref);
  const { data, error } = useLoad(() => api("notes/totals"), []);
  const go = (action, topic) => { launch({ action, notes: topic ? `Topic: ${topic}` : "All notes", from: { view: "Notes" } }); ref.current.close(); };
  const both = (topic) => html`<button onClick=${() => go("notes-compact", topic)}>Compact…</button><button onClick=${() => go("notes-sweep", topic)}>Sweep…</button>`;
  const topics = data ? Object.entries(data.by_topic || {}).sort((a, b) => b[1] - a[1]) : [];
  return html`<dialog class="flyout" ref=${ref} onClose=${onClose} aria-labelledby="kn-keep">
    <div class="row" style="justify-content: space-between"><h2 id="kn-keep">Keep notes useful</h2><button class="plain" onClick=${() => ref.current.close()}>Close</button></div>
    <div class="stack" style="gap: 16px">
      <p class="small">Compact: an Archivist proposes note operations (merge, distil, supersede, answer), each with its exact command, and you apply them; nothing is deleted. Sweep: a docs writer drafts issues for what belongs in the docs.</p>
      <div class="row" style="gap: 6px"><b style="flex: 1">All notes</b>${both(null)}</div>
      <${Err} text=${error} />
      ${data && !data.here && html`<p class="small" role="status">${data.says}</p>`}
      ${data && data.here && !data.source && html`<p class="small soft">Totals come from a search: search first, and the totals of its rows show here.</p>`}
      ${data && data.source && html`<p class="small soft">Counted from your last search's ${count(data.rows, "row")}: the notes tool has no totals of its own yet.</p>
        <section class="stack tight" aria-label="Per label"><span class="eyebrow">Per label</span>
          <ul class="stack tight">${Object.entries(data.by_label).map(([state, n]) => html`<li class="row" style="gap: 8px"><span class="badge ${trustOf(state)[1]}">${trustOf(state)[0]}</span><span>${n}</span></li>`)}</ul></section>
        <section class="stack tight" aria-label="Per topic"><span class="eyebrow">Per topic</span>
          <ul class="stack" style="gap: 6px">${topics.map(([topic, n]) => html`<li class="row" style="gap: 6px"><span class="mono small" style="flex: 1; overflow-wrap: anywhere">${topic} · ${n}</span>${both(topic)}</li>`)}</ul></section>`}
    </div></dialog>`;
}

function NotesPage() {
  const status = useLoad(() => api("notes"), [], 60000);
  const [words, setWords] = useState(""); // never in the address, which the Steward's panel reads (009 FR-001)
  const [found, setFound] = useState(null);
  const [searched, setSearched] = useState("");
  const [indexing, setIndexing] = useState(false);
  const [keep, setKeep] = useState(false);
  const [copied, setCopied] = useState(false);
  const act = useAct();
  // Rows from an earlier search never stay under new words, and "show more" means more of what was searched.
  const search = (asked, limit) => act.run(async () => {
    if (limit === NOTES_PAGE) setFound(null);
    setSearched(asked);
    // The tool brings its index up to date on each search: say so while it does (009 FR-004).
    const poll = setInterval(() => api("notes").then((s) => setIndexing(Boolean(s.indexing))).catch(() => {}), 700);
    try { setFound(await post("notes/find", { words: asked, limit })); } finally { clearInterval(poll); setIndexing(false); }
  });
  const missing = found && !found.here ? found.says : status.data && !status.data.here ? status.data.says : null;
  const rows = found && found.here ? found.rows : [];
  const more = found && found.here && found.total > rows.length;
  const atLimit = more && rows.length >= NOTES_MOST;
  return html`<main class="page close" aria-labelledby="h-notes">
    <div class="row" style="justify-content: space-between; align-items: flex-end">
      <div class="stack tight"><h1 id="h-notes">Notes</h1>
        <span class="small soft">The shared notes, by word, as <span class="mono">notes find</span> searches them. Only a login reads this page. Every row says how far it can be trusted, and current comes first.</span></div>
      <button disabled=${Boolean(missing)} onClick=${() => setKeep(true)}>Keep notes useful…</button></div>
    ${missing && html`<div class="panel stack tight" style="padding: 14px" role="status"><b>The notes tool isn't here.</b><span style="overflow-wrap: anywhere">${missing}</span></div>`}
    ${act.error && html`<div class="error" role="alert"><b>The notes tool failed.</b> It said: <span style="overflow-wrap: anywhere">${act.error}</span></div>`}
    <${Err} text=${status.error} />
    <form class="row" style="gap: 8px" role="search" onSubmit=${(e) => { e.preventDefault(); if (words.trim()) search(words, NOTES_PAGE); }}>
      <label class="row small" style="gap: 6px; flex: 1">Look for
        <input type="search" style="flex: 1; min-width: 0" maxlength="500" value=${words} onInput=${(e) => setWords(e.target.value)} /></label>
      <button class="primary" type="submit" disabled=${act.busy || !words.trim() || Boolean(missing)}>${act.busy ? "Searching…" : "Search"}</button>
      ${(indexing || (status.data && status.data.indexing)) && html`<span class="badge sev-info" role="status">indexing</span>`}</form>
    ${!found && !missing && html`<div class="stack" style="gap: 8px"><p class="small soft">Search by words, then press Search. What each label means:</p><${TrustLegend} /></div>`}
    ${found && found.here && html`<div class="stack" style="gap: 4px">
      <p role="status" class="small">${rows.length ? `${found.says}${more ? `, showing ${rows.length}` : ""}.` : `Nothing matches “${searched}”.`}</p>
      ${found.warnings.map((w) => html`<p class="small" role="status" style="overflow-wrap: anywhere"><b>Warning:</b> ${w}</p>`)}
      ${rows.map((r, i) => html`<${NoteRow} key=${`${r.where}-${i}`} r=${r} />`)}
      ${more && !atLimit && html`<div class="row"><button disabled=${act.busy} onClick=${() => search(searched, Math.min(rows.length + NOTES_PAGE, NOTES_MOST))}>Show ${Math.min(NOTES_PAGE, NOTES_MOST - rows.length, found.total - rows.length)} more</button>
        <span class="small soft">${found.total - rows.length} more match.</span></div>`}
      ${atLimit && html`<div class="panel stack tight" style="padding: 14px" role="status"><b>That's as many as this page shows (${NOTES_MOST}).</b>
        <span class="small">Narrow the words, or list all ${found.total} in a terminal:</span>
        <div class="row" style="gap: 8px"><code class="mono small" style="flex: 1; overflow-wrap: anywhere">${notesCommand(searched, found.total)}</code>
          <button onClick=${async () => setCopied(await copyText(notesCommand(searched, found.total)))}>${copied ? "Copied" : "Copy"}</button></div></div>`}</div>`}
    ${keep && html`<${KeepNotesUseful} onClose=${() => setKeep(false)} />`}
  </main>`;
}

// 001 FR-001. Device is on Overview,
// decisions are in Needs you; their old addresses go there (Hub's MOVED).
const NAV = [["overview", "Overview"], ["roadmap", "Roadmap"], ["work", "Work"], ["knowledge", "Knowledge"], ["notes", "Notes"], ["shells", "Sessions"]];

// --- the Steward ---------------------------------------------------------------------------------
const STEWARD = "steward";
const SEEN_KIND = { issues: "issue", prs: "pull request", actions: "run" };
const SEEN_SCREEN = { overview: "Overview", roadmap: "Roadmap", work: "Work", knowledge: "Knowledge", notes: "Notes", shells: "Sessions", design: "Sessions" };
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

// The repositories chosen on the page, from the address: Work's one (or a list), Knowledge's list. Knowledge reads its list
// with this too, so the page and the Steward's chips name the same ones. hubd checks them again.
const SEEN_REPOS_MOST = 10;
function seenRepos(value) {
  const names = String(value || "").split(",").filter((r) => /^\.?[A-Za-z0-9_][A-Za-z0-9._-]{0,99}$/.test(r));
  return [...new Set(names)].slice(0, SEEN_REPOS_MOST);
}

function seenFrom(route) {
  const q = route.query;
  const moved = movedRoute(route);
  const path = moved.path, tab = path === "work" ? moved.query.tab || "prs" : path;
  // From the address, which a link can fill with anything. Same pattern as hubd's.
  const item = (repo, n) => (/^[A-Za-z0-9._-]{1,100}$/.test(repo || "") && /^[0-9]{1,20}$/.test(n || "") ? `${repo}#${n}` : null);
  const repos = path === "work" ? seenRepos(moved.query.repo) : path === "knowledge" ? seenRepos(moved.query.repos) : [];
  if (path === "work" && item(q.at || q.repo, q.item)) return { screen: "Work", kind: SEEN_KIND[tab] || null, selection: item(q.at || q.repo, q.item), repos };
  if (path === "work" && tab === "queue") return { screen: "Queue", kind: null, selection: null, repos };
  return { screen: SEEN_SCREEN[path] || "Overview", kind: null, selection: null, repos };
}

// 010 FR-002: open beside Overview, Roadmap, Work and a work item; a rail beside Sessions, Knowledge and Notes. What you
// choose on a view is kept for that view, in this browser.
const STEWARD_OPEN = ["Overview", "Roadmap", "Work", "Work item", "Queue"];
const stewardView = (seen) => (seen.screen === "Work" && seen.selection ? "Work item" : seen.screen);
function readPanels() {
  try { const v = JSON.parse(localStorage.getItem("steward-panel") || "{}"); return v && typeof v === "object" ? v : {}; } catch { return {}; }
}
function panelOpen(view) {
  const kept = readPanels()[view];
  return kept === "open" ? true : kept === "rail" ? false : STEWARD_OPEN.includes(view);
}
function keepPanel(view, open) {
  try { localStorage.setItem("steward-panel", JSON.stringify({ ...readPanels(), [view]: open ? "open" : "rail" })); } catch { /* it only helps */ }
}
// 010 FR-001: the panel's width, 320 to 760 px, kept per viewer in this browser.
const STEWARD_WIDTH = { min: 320, max: 760, start: 440, step: 16 };
const clampWidth = (w, max = STEWARD_WIDTH.max) => Math.min(max, Math.max(STEWARD_WIDTH.min, Math.round(Number(w) || STEWARD_WIDTH.start)));
// Up to 1000 px wide the panel takes at most 45 % of the window (style.css has the same cap), so the widest it can be
// is that; the handle reports this as its maximum, and the width it reports is the one drawn. Wider, the spec's 760.
const widthRoom = (inner) => (inner <= 1000 ? Math.max(STEWARD_WIDTH.min, Math.min(STEWARD_WIDTH.max, Math.floor(inner * 0.45))) : STEWARD_WIDTH.max);
function useWidthRoom() {
  const [room, setRoom] = useState(() => widthRoom(window.innerWidth));
  useEffect(() => {
    const on = () => setRoom(widthRoom(window.innerWidth));
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);
  return room;
}
function readWidth() {
  try { return clampWidth(localStorage.getItem("steward-width")); } catch { return STEWARD_WIDTH.start; }
}

function WidthHandle({ width, max, onWidth }) {
  const drag = useRef(null);
  const set = (w) => onWidth(clampWidth(w, max));
  const key = (e) => {
    const step = e.shiftKey ? STEWARD_WIDTH.step * 4 : STEWARD_WIDTH.step;
    // The panel is on the right: Left widens it, Right narrows it. Home and End go to aria-valuemin and aria-valuemax, the
    // panel's narrowest and widest, as a window splitter's do for the pane its value is.
    const next = { ArrowLeft: width + step, ArrowRight: width - step, Home: STEWARD_WIDTH.min, End: max }[e.key];
    if (next === undefined) return;
    e.preventDefault();
    set(next);
  };
  const down = (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    drag.current = { x: e.clientX, w: width };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const move = (e) => { if (drag.current) set(drag.current.w + (drag.current.x - e.clientX)); };
  const up = () => { drag.current = null; };
  return html`<div class="dock-handle" role="separator" tabindex="0" aria-orientation="vertical" aria-label="Steward panel width"
    aria-valuemin=${STEWARD_WIDTH.min} aria-valuemax=${max} aria-valuenow=${width} aria-valuetext=${`${width} pixels`}
    title="Drag, or use the arrow keys, to resize" onKeyDown=${key} onPointerDown=${down} onPointerMove=${move} onPointerUp=${up} onPointerCancel=${up}></div>`;
}

// 010 FR-006: what the Steward is asked, in the words of the chips, and your own after it.
const planWords = (chips, own) => {
  const seen = chips.map((c) => c.label).join(" · ");
  const ask = `Plan new work from what I'm looking at in the hub (${seen}). Suggest it with plan_work or suggest_session, so it opens Launch for me.`;
  return own.trim() ? `${ask}\n\n${own.trim()}` : ask;
};

function PlanWithSteward({ chips, running, where, onClose }) {
  const [own, setOwn] = useState("");
  const [note, setNote] = useState("");
  const act = useAct();
  const text = planWords(chips, own);
  const room = MAX_MESSAGE - planWords(chips, "x").length + 1;
  const off = running ? "" : "Start the Steward first: it plans only while it runs.";
  const send = () => act.run(async () => {
    const r = await post("agents/say", { name: STEWARD, text, where });
    setOwn("");
    setNote(r.sent ? "Sent to the Steward as your turn." : `Queued (${r.queued} waiting). It goes when the Steward's turn ends.`);
  });
  return html`<div class="dock-plan stack tight" role="group" aria-labelledby="dock-plan-h">
    <span id="dock-plan-h" class="eyebrow">Plan new work with the Steward</span>
    <span class="small soft">It gets what the chips above show, and your words.</span>
    <label class="small" for="dock-plan-own">Your words (optional)</label>
    <textarea id="dock-plan-own" rows="2" maxlength=${Math.max(0, room)} disabled=${!!off} value=${own} placeholder="Start with the failing runs."
      onInput=${(e) => setOwn(e.target.value)}
      onKeyDown=${(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && !off && !act.busy) { e.preventDefault(); send(); } }}></textarea>
    <div class="row" style="gap: 8px; justify-content: space-between">
      <span role="status" class="small soft">${off || (act.busy ? "Sending…" : note)}</span>
      <span class="row" style="gap: 8px"><button class="plain" onClick=${onClose}>Close</button>
        <button class="primary" disabled=${!!off || act.busy || text.length > MAX_MESSAGE} onClick=${send}>Send to the Steward</button></span></div>
    <${Err} text=${act.error} /></div>`;
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
  // The panel's head has the Steward's name, model, state and Stop: below it is the compact SessionView (004 FR-001).
  const session = { name: STEWARD, attached: 0, agent: { persona: STEWARD, persona_name: "Steward", waiting: words === "Waiting for you", idle: words === "Idle", ended: false } };
  return html`<${SessionView} session=${session} mode="compact" asks=${asks} seen=${seen} buttons=${buttons} queued=${state.queued} after=${reload} onGone=${reload}>
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

// 001 FR-008: at phone width the Steward is a floating button that opens it as a full sheet. Opening it there leaves the
// open-or-rail choice of the wide panel alone.
function StewardSheet({ onClose, children }) {
  const ref = useRef(null);
  useModal(ref);
  return html`<dialog ref=${ref} class="sheet steward-sheet" aria-labelledby="dock-h" onClose=${onClose}>${children}</dialog>`;
}

function Steward({ route, asks }) {
  const seen = seenFrom(route);
  const view = stewardView(seen);
  const phone = usePhone();
  const [panels, setPanels] = useState(() => ({ [view]: panelOpen(view) }));
  const [sheet, setSheet] = useSheet(view, phone);  // on a phone: the view the sheet was opened on
  const open = phone ? sheet === view : view in panels ? panels[view] : panelOpen(view);
  const rail = !open;
  const setRail = (next) => {
    if (phone) return setSheet(next ? null : view);
    keepPanel(view, !next);
    setPanels({ ...panels, [view]: !next });
  };
  const [width, setWidthState] = useState(readWidth);
  const room = useWidthRoom();
  const shown = Math.min(width, room);  // what is drawn, and what the handle reports
  const setWidth = (w) => { setWidthState(w); try { localStorage.setItem("steward-width", String(w)); } catch { /* it only helps */ } };
  const [modelOpen, setModelOpen] = useState(false);
  const [planning, setPlanning] = useState(false);
  const [confirm, dialog] = useConfirm();
  const { data: loaded, reload } = useLoad(() => post("agents/state", { name: STEWARD }), [], rail ? 15000 : 3000);
  // A failed read keeps what we knew, or a brief hubd error would close the terminal and offer Start.
  const known = useRef(null);
  if (loaded) known.current = loaded;
  const state = known.current;
  const { data: buttons } = useLoad(() => post("agents/buttons").then((r) => r.buttons).catch(() => []), []);
  const words = state ? state.state : "Not started";
  const running = words !== "Not started" && words !== "Stopped";
  // 010 FR-004: hubd checks what the page sees, writes the line the Steward gets, and answers with the chips made from
  // the same values. The line is one per session and the last page to write it wins (another tab, a phone), so once
  // the Steward has a folder the chips are hubd's own for the line on disk (state.sees), read again after each write.
  const seenKey = JSON.stringify([seen.screen, seen.kind, seen.selection, seen.repos]);
  const [told, setTold] = useState(null);
  const toldWith = useRef(null);  // the state read before this page's last write: its sees are older than the answer
  const [back, setBack] = useState(0);
  useEffect(() => {
    // Back on this tab or window: it tells the Steward its own place again. A hidden tab writes nothing.
    const again = () => { if (!document.hidden) setBack((n) => n + 1); };
    window.addEventListener("focus", again);
    document.addEventListener("visibilitychange", again);
    return () => { window.removeEventListener("focus", again); document.removeEventListener("visibilitychange", again); };
  }, []);
  useEffect(() => {
    if (document.hidden) return undefined;
    let live = true;
    post("agents/context", { name: STEWARD, screen: seen.screen, kind: seen.kind, selection: seen.selection, repos: seen.repos })
      .then((r) => { if (live) { toldWith.current = known.current; setTold({ key: seenKey, chips: r.sees || [] }); reload(); } })
      .catch(() => { if (live) setTold({ key: seenKey, chips: null }); });
    return () => { live = false; };
  }, [running, seenKey, back]);
  const onDisk = state && state.sees && state !== toldWith.current ? state.sees : null;
  const chips = onDisk || (told && told.key === seenKey ? told.chips : null);
  // 010 FR-005: what from the Steward waits for you, as Needs you counts it.
  const waiting = asks.interactions.items.filter((r) => r.status === "pending" && r.session === STEWARD).length;
  const stopping = useAct(reload);
  // 004 FR-011: only after a confirmation. Not discarded: "Stopped" offers Resume, with the conversation.
  const stop = () => confirm(
    { title: "Stop the Steward?", danger: true, label: "Stop session",
      text: "Stops the Steward: Claude and everything running in its terminal. Its conversation can be resumed later." },
    () => stopping.run(() => api(`shells/${encodeURIComponent(STEWARD)}`, { method: "DELETE" })),
  );
  const plan = () => { setRail(false); setPlanning(true); };
  const fabLabel = `Open the Steward, ${words}${waiting ? `, ${waiting} waiting for you` : ""}`;
  // The floating button stays while the sheet is open, so focus has it to go back to.
  const fab = phone && html`<button class="dock-s steward-fab" aria-haspopup="dialog" aria-label=${fabLabel} onClick=${() => setRail(false)}>S${waiting > 0 && html`<span class="dock-count" aria-hidden="true">${waiting}</span>`}</button>`;
  if (phone && rail) return fab;
  if (rail) {
    return html`<nav class="dock-rail" aria-label="Steward">
      <button class="dock-s" aria-label=${fabLabel} title=${`Steward: ${words}`} onClick=${() => setRail(false)}>S${waiting > 0 && html`<span class="dock-count">${waiting}</span>`}</button>
      <button class="dock-item" aria-label="Plan new work with the Steward" title="Plan new work with the Steward" onClick=${plan}>＋</button></nav>`;
  }
  const body = html`${dialog}
    <div class="dock-head"><span class="dock-s small" aria-hidden="true">S</span>
      <span class="stack" style="gap: 0; flex: 1; min-width: 0"><h2 id="dock-h" style="font-size: 17px; font-weight: 600">Steward</h2>
        <button class="link dock-modelname mono" aria-expanded=${modelOpen ? "true" : "false"} aria-label=${`Steward model${state && state.model ? `: ${state.model}` : ""}. Change`} onClick=${() => setModelOpen(!modelOpen)}>${(state && state.model) || "model"}</button></span>
      <span class="badge ${STATE_BADGE[words] || ""}">${words}</span>
      ${state && state.machine && html`<${StateChip} machine=${state.machine} ended=${!running} />`}
      ${running && html`<button class="plain" disabled=${stopping.busy} onClick=${stop}>Stop…</button>`}
      ${phone ? html`<button class="square" aria-label="Close the Steward" onClick=${(e) => e.currentTarget.closest("dialog").close()}>×</button>`
        : html`<button class="square" aria-label="Collapse the Steward to a rail" onClick=${() => setRail(true)}>›</button>`}</div>
    <${StewardModel} running=${running} current=${state && state.model} open=${modelOpen} />
    <${Err} text=${stopping.error} />
    <div class="dock-sees"><${Eyebrow} soft>Sees<//>${chips ? chips.map((c) => html`<span class="label ${c.kind === "view" ? "" : "mono"}" style="padding-right: 8px">${c.label}</span>`)
      : told ? html`<span class="small soft">hubd didn't answer: the Steward may not know where you are.</span>` : html`<span class="label" style="padding-right: 8px">${seen.screen}</span>`}</div>
    ${waiting > 0 && html`<button class="dock-waiting row" onClick=${() => needsYou({ filter: "steward" })}><span>${count(waiting, "interaction")} from the Steward ${waiting === 1 ? "waits" : "wait"} for you</span><span aria-hidden="true">→</span></button>`}
    ${planning ? html`<${PlanWithSteward} chips=${chips || [{ kind: "view", label: seen.screen }]} running=${running} where=${seen.screen} onClose=${() => setPlanning(false)} />`
      : html`<button class="plain dock-planbtn" onClick=${() => setPlanning(true)}>＋ Plan new work with the Steward</button>`}
    <${StewardSession} state=${state || { state: "Not started", queued: 0 }} seen=${seen} buttons=${buttons} reload=${reload} asks=${asks} />
    <p class="small soft" style="margin: 0; padding: 0 12px 12px">A configured session like any other: no shell, reads everything, and every write asks you first.</p>`;
  if (phone) return html`${fab}<${StewardSheet} onClose=${() => setRail(true)}><div class="dock">${body}</div><//>`;
  return html`<aside class="dock" aria-labelledby="dock-h" style=${`--dock-w: ${shown}px`}>
    <${WidthHandle} width=${shown} max=${room} onWidth=${setWidth} />${body}</aside>`;
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
  // Launch records: what LaunchModal draws its stage from, and SetAside reads.
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
  const phone = usePhone();
  const [menu, setMenu] = useSheet(route.path, phone); // the Menu sheet, at phone width

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
  const views = { overview: Overview, roadmap: Roadmap, work: Work, knowledge: Knowledge, notes: NotesPage, shells: Sessions, design: DesignView, apps: AppsPage, workflows: WorkflowsPage };
  // #/workflows/<name>: the editor of one workflow (012 FR-061).
  const [top, sub] = path.split("/");
  const View = views[sub !== undefined && top === "workflows" ? top : path] || Overview;
  const pageQuery = top === "workflows" && sub ? { ...query, name: decodeURIComponent(sub) } : query;
  const here = path;
  const unreachable = Boolean(hostPoll.error || listed.error);
  const newWork = () => launch({ from: { view: SEEN_SCREEN[here] || "Overview" } });
  const header = phone ? html`<header class="top phone">
      <button class="primary new-work" aria-label="New work" onClick=${newWork}>＋ New</button>
      <${MenuButton} asks=${asks} onOpen=${() => setMenu(true)} /></header>`
    : html`<header class="top"><${Logo} />
      <nav aria-label="Primary">${NAV.map(([key, label]) => html`<a href=${key === "shells" ? hash("shells", { tab: "all" }) : `#/${key}`} aria-current=${here === key ? "page" : null}>${label}</a>`)}</nav>
      <div class="end">
        <${NeedsButton} asks=${asks} />
        <button class="primary new-work" onClick=${newWork}>＋ New work</button>
        ${!host.gh && html`<span class="badge bad">no gh on the host</span>`}
        ${!host.tmux && html`<span class="badge bad">no tmux on the host</span>`}
        <${UsageMeter} />
        <span class="small whoami"><span class="mono">${host.user}</span>${host.hubd && html` · <span class="soft">hubd</span> <span class="mono soft">${host.hubd}</span>`}</span>
        <button class="plain" onClick=${async () => { await post("logout"); onOut(); }}>Sign out</button>
      </div></header>`;
  return html`<div class="with-dock"><div class="dock-main">
    ${header}
    ${menu && phone && html`<${MenuSheet} here=${here} asks=${asks} host=${host} onOut=${onOut} onClose=${() => setMenu(false)} />`}
    ${unreachable && html`<div class="unreachable" role="status">hubd can't be reached — showing what was last read.</div>`}
    <${View} key=${path + JSON.stringify(path === "shells" || path === "work" || path === "knowledge" ? {} : query)} query=${pageQuery} asks=${asks} /></div>
    <${Steward} route=${route} asks=${asks} />
    ${launching && html`<${LaunchModal} key=${launching.key} open=${launching} work=${asks.work} asks=${asks} reload=${reloadAll}
      onClose=${() => setLaunching(null)} onBehind=${(b) => { setLaunching(null); setBehind(b); }} />`}
    ${needs && html`<${NeedsYouModal} key=${needs.key} initial=${needs} data=${inter} asks=${asks} onClose=${closeNeeds} />`}
    ${behind && html`<div role="status" class="nw-toast"><span style="flex: 1">${behind.name ? html`<a class="mono" style="font-weight: 600" href=${hash("shells", { tab: "all", name: behind.name })} onClick=${() => setBehind(null)}>${behind.name}</a>` : html`<b>${behind.title}</b>`} goes on in the background. Its asks and its result arrive in <button class="link" onClick=${() => needsYou()}>Needs you</button>.</span>
      <button class="plain" onClick=${() => launch({ id: behind.id })}>Reopen</button><button class="square" aria-label="Dismiss" onClick=${() => setBehind(null)}>×</button></div>`}</div>`;
}

render(html`<${App} />`, document.getElementById("root"));
