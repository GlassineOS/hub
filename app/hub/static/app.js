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
function useLoad(loader, deps, every) {
  const [state, set] = useState({ loading: true });
  const seq = useRef(0);
  const reload = useCallback(async () => {
    const mine = ++seq.current;
    set((s) => ({ ...s, loading: true }));
    try {
      const data = await loader();
      if (mine === seq.current) set({ data, loading: false });
    } catch (error) {
      if (mine === seq.current) set({ error: error.message, loading: false });
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
      <button onClick=${() => planWork({ action: "new-security-audit", repo: repo.name })}>＋ Audit or plan…</button>
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
  return html`<a class="stat" href=${hash("docs")}><${Eyebrow} soft>Docs index<//>
    <b>${error ? "unknown" : data ? data.state : "…"}</b>
    <span class="small soft">${data ? `site ${data.published.slice(0, 7)} · head ${data.head.slice(0, 7)}` : error || " "}</span></a>`;
}

function Overview() {
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
        <button onClick=${() => planWork({ action: "new-roadmap-item", repo: "hub" })}>＋ Roadmap item</button>
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

// --- agents: one click on the object ---------------------------------------------------
let advancedHandoff = null;

function specRows(config, action) {
  const rows = [["Persona", config.persona], ["Model", `${config.model} · ${config.effort}`]];
  if (action.full) rows.push(["Tools", "full Claude Code"]);
  else rows.push(["Hub tools", config.hub_tools.join(", ") || "none"], ["Tools", config.tools.join(", ") || "none"]);
  return rows;
}

const STEER_CHIPS = {
  pr: ["error paths first", "keep the diff small", "check it against the docs", "add tests"],
  issue: ["only propose, don't apply", "look for duplicates", "keep the change small"],
  run: ["compare with earlier runs", "don't touch the runner image"],
};
const PIN_WORDS = { thread: "Review thread", ref: "Issue / PR", file: "Repo file", docs: "Docs page", url: "Link", text: "Text snippet" };
const PIN_HINTS = { ref: "hub#44", file: "kernel:drivers/gpu/drm/epd/epd_lut.c", docs: "docs path", text: "Something the agent should know" };
const pinKind = (v) => (/^https?:/.test(v) ? "url" : /#\d/.test(v) ? "ref" : v.indexOf(":") > 0 ? "file" : "docs");

// What you add to an item survives moving around the page, until you start or leave the hub.
const steering = new Map();

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

// What a planner is doing or came back with, per item, so moving to another item doesn't throw it away.
const plans = new Map();
const planErrors = new Map();
// A list row's start button. A click, never part of the address: a link or a reload doesn't spend a planner run.
let rowPlan = null;

function Spawn({ kind, repo, number, failing, session, phase, threads, onStarted, onPhase }) {
  const { data } = useLoad(() => api(`agents/actions${params({ object: kind })}`), [kind]);
  const key = `${kind}/${repo}/${number}`;
  const [plan, setPlanState] = useState(() => plans.get(key) || null); // { action, phase, config, cost, picked }
  const [planNote, setPlanNote] = useState(null);
  const setPlan = (next) => { if (next) plans.set(key, next); else plans.delete(key); setPlanState(next); };
  const [steer, setSteerState] = useState(() => ({ notes: "", pins: [], also: [], planner: PLANNER_DEFAULT, ...steering.get(key) }));
  const [alsoText, setAlsoText] = useState("");
  const [open, setOpen] = useState(false);
  const setSteer = (patch) => setSteerState((s) => { const next = { ...s, ...patch }; steering.set(key, next); return next; });
  const clearSteer = () => { steering.delete(key); setSteerState({ notes: "", pins: [], also: [], planner: PLANNER_DEFAULT }); };
  const canCover = kind === "issue" && (data || []).some((a) => a.full);
  const addAlso = () => { const n = Number(alsoText.replace(/^.*#/, "").trim()); if (Number.isInteger(n) && n > 0 && n !== number && !steer.also.includes(n)) setSteer({ also: [...steer.also, n] }); setAlsoText(""); };
  const act = useAct();
  const openThreads = threads ? threads.open : 0;
  const reviewCount = threads ? threads.reviews : 0;  // a review can say it all in its text, with no threads
  const threadPins = threads ? threads.pins : [];
  const offered = (data || []).filter((a) => (!a.when || a.when === (failing ? "failing" : "not-failing")) && (!a.needs || (a.needs === "review" && openThreads + reviewCount > 0))).sort((a, b) => Boolean(b.needs) - Boolean(a.needs));
  const sent = () => ({ notes: steer.notes, pins: [...steer.pins, ...threadPins] });
  const titleOf = (a) => (a.needs === "review" ? `${a.title} · ${threadPins.length ? count(threadPins.length, "ticked thread") : openThreads === 1 ? "1 open thread" : openThreads ? `all ${openThreads} threads` : count(reviewCount, "review")}` : a.title);
  const go = (a) => {
    if (!a.plan) {
      act.run(async () => { onStarted(await post("agents/run", { action: a.id, repo, number, ...sent() })); clearSteer(); });
      return;
    }
    setPlanNote(null); planErrors.delete(key);
    setPlan({ action: a, phase: "planning" });
    act.run(async () => {
      try {
        const r = await post("agents/plan", { action: a.id, repo, number, ...sent(), planner_model: steer.planner });
        setPlan({ action: a, phase: "ready", config: a.full && steer.also.length ? { ...r.config, also_numbers: steer.also } : r.config, cost: r.planner_cost_usd, picked: r.config.model, planner: steer.planner });
      } catch (e) {
        planErrors.set(key, e.message);
        setPlan(null);
        throw e;
      }
    });
  };
  const start = () => act.run(async () => { onStarted(await post("agents/start", { config: plan.config })); setPlan(null); clearSteer(); });
  const chooseModel = (model) => setPlan({ ...plan, config: { ...plan.config, model } });
  const advanced = () => { advancedHandoff = plan.config; };
  useEffect(() => {
    if (!rowPlan || rowPlan.key !== key || !data) return;
    const { action, title } = rowPlan;
    rowPlan = null;
    const a = offered.find((x) => x.id === action);
    if (a && a.plan) go(a);
    else setPlanNote(`${title} isn't offered for this item now, so no planner ran.`);
  }, [data]);
  // A plan started before you came back to this item finishes in the other instance of this panel.
  useEffect(() => {
    if (!plan || plan.phase !== "planning") return undefined;
    const timer = setInterval(() => {
      const now = plans.get(key) || null;
      if (now !== plan) { setPlanState(now); setPlanNote(planErrors.get(key) || null); }
    }, 1000);
    return () => clearInterval(timer);
  }, [plan]);
  const noun = { pr: "pull request", issue: "issue", run: "run" }[kind];
  const w = session && session.agent && session.agent.waiting;
  return html`<section class="spawn keycap" aria-labelledby="h-claude">
    <div class="row" style="gap: 4px 12px; align-items: baseline"><h2 id="h-claude" class="row" style="gap: 8px; font-size: 19px; font-weight: 600"><${TermIcon} />Claude</h2>
      <span class="small soft">Start an agent session for this ${noun}.</span></div>
    <${Err} text=${planNote} />
    ${!plan && html`${open
      ? html`<div class="stack" style="gap: 8px; padding: 12px 14px; background: var(--sheet); border-radius: 12px">
          <${SteerFields} kind=${kind} notes=${steer.notes} pins=${steer.pins} onNotes=${(notes) => setSteer({ notes })} onPins=${(pins) => setSteer({ pins })} />
          ${canCover && html`<div class="stack split-rule" style="gap: 6px"><span class="eyebrow">Also covers · ${steer.also.length || "none"}</span>
            <span class="small soft">Other issues the same session should finish. Each one shows the session in Work, and the PR closes all of them. Applies to sessions that write code.</span>
            <div class="row" style="gap: 6px"><span class="label mono" style="padding-right: 8px; background: var(--mark)">${repo}#${number} · primary</span>
              ${steer.also.map((n) => html`<button class="label mono" style="padding-right: 8px" aria-label=${`Remove ${repo}#${n}`} onClick=${() => setSteer({ also: steer.also.filter((x) => x !== n) })}>${repo}#${n} ×</button>`)}
              <input class="mono" style="width: 110px" placeholder="issue number" aria-label=${`Another issue of ${repo} to cover`} value=${alsoText} onInput=${(e) => setAlsoText(e.target.value)} onKeyDown=${(e) => { if (e.key === "Enter") { e.preventDefault(); addAlso(); } }} />
              <button class="addlabel" disabled=${!alsoText.trim()} onClick=${addAlso}>+ add</button></div></div>`}
          <div class="row split-rule" style="gap: 10px 16px; align-items: flex-end"><${PlannerModel} id="spawn-pm" value=${steer.planner} onChange=${(planner) => setSteer({ planner })} />
            <span class="small soft" style="flex: 1 1 200px">Model for the throwaway planner run that writes the spec. The agent’s own model is picked on the spec.</span></div>
          <button class="link" aria-expanded="true" style="align-self: flex-end" onClick=${() => setOpen(false)}>Hide, and keep what you added</button></div>`
      : html`<div class="row"><button class="addlabel" aria-expanded="false" onClick=${() => setOpen(true)}>+ Notes and context for the planner</button>
          <span class="small soft">${steer.notes.trim() ? `“${steer.notes.length > 60 ? `${steer.notes.slice(0, 60)}…` : steer.notes}”` : "no notes"} · ${steer.pins.length + threadPins.length ? `${steer.pins.length + threadPins.length} pinned` : "nothing pinned"}</span></div>`}
    <div class="row">${offered.map((a, i) => html`<button class=${i === 0 ? "primary" : ""} title=${`${a.summary} ${a.ceiling}`} disabled=${act.busy} onClick=${() => go(a)}><${TermIcon} />${titleOf(a)}</button>`)}</div>`}
    ${!plan && !session && html`<span class="small soft">The planner runs first, and you confirm its spec.${offered.filter((a) => !a.plan).map((a) => ` ${a.title} starts at once.`)}</span>`}
    ${plan && plan.phase === "planning" && html`<div role="status" class="split-rule">
      <span class="row" style="font-weight: 600"><${StateIcon} kind="run" />Planning “${plan.action.title}”</span>
      <span class="mono soft" style="font-size: 12.5px">claude -p · ${NW_MODEL[steer.planner] || steer.planner} · read-only hub tools · up to a few minutes</span>
      ${(steer.notes.trim() || steer.pins.length + threadPins.length > 0) && html`<span class="small soft">With your notes and ${count(steer.pins.length + threadPins.length, "pin")}.</span>`}</div>`}
    ${plan && plan.phase === "ready" && html`<div class="split-rule">
      <${Eyebrow}>Spec from planner · ${plan.action.title}<//>
      <dl class="defs">${(plan.config.also_numbers || []).length > 0 && html`<dt>Covers</dt><dd>${repo}#${number} (primary), ${plan.config.also_numbers.map((n) => `${repo}#${n}`).join(", ")}</dd>`}
        ${specRows(plan.config, plan.action).map(([k, v]) => html`<dt>${k}</dt><dd>${v}</dd>`)}
        ${plan.config.notes && html`<dt>Your notes</dt><dd>${plan.config.notes}</dd>`}
        ${plan.config.pins.length > 0 && html`<dt>Pinned</dt><dd>${plan.config.pins.map((p) => p.label).join(" · ")}</dd>`}</dl>
      ${plan.action.models.length > 1 && html`<div class="stack tight"><span class="eyebrow" id="spawn-model">Model for this session</span>
        <div role="radiogroup" aria-labelledby="spawn-model" class="seg" style="align-self: flex-start">${plan.action.models.map((m) => html`<button role="radio" aria-checked=${plan.config.model === m ? "true" : "false"} onClick=${() => chooseModel(m)}>${m}</button>`)}</div>
        <span class="small soft">${plan.config.model === plan.picked ? `${plan.picked}: the planner's choice.` : `${plan.config.model}: your choice. The planner suggested ${plan.picked}.`}</span></div>`}
      ${plan.config.docs.length > 0 && html`<div class="stack tight"><${Eyebrow}>Context · docs search<//>
        ${plan.config.docs_query && html`<span class="soft" style="font-size: 13px">Planner searched for <span class="mono" style="color: var(--ink)">“${plan.config.docs_query}”</span>:</span>`}
        <ul class="stack" style="gap: 4px">${plan.config.docs.map((d) => html`<li class="passage"><span><b>${d.link}</b><span class="soft" style="font-size: 13px">${d.why}</span></span></li>`)}</ul></div>`}
      ${plan.config.brief && html`<div class="stack" style="gap: 4px"><${Eyebrow}>Briefing<//><pre class="codeblock" style="white-space: pre-wrap; font-size: 12.5px">${plan.config.brief}</pre></div>`}
      <span class="soft" style="font-size: 13px">${plan.action.ceiling}${plan.cost != null ? ` Planning cost $${plan.cost.toFixed(2)}.` : ""}</span>
      <div class="row">
        <button class="primary" disabled=${act.busy} onClick=${start}>Start session</button>
        <a class="button" href=${hash("launch", { action: plan.action.id, repo, number })} onClick=${advanced}>Advanced…</a>
        <button onClick=${() => { setPlan(null); setOpen(true); }}>Edit notes and context</button>
        <button disabled=${act.busy} onClick=${() => go(plan.action)}>Re-plan with current notes</button>
        <button class="link" onClick=${() => setPlan(null)}>Discard</button></div></div>`}
    ${session && phase === "embedded" && html`<div role="status" class="notice"><span><span class="mono">${session.name}</span> is open below</span>
      <button class="plain" onClick=${() => onPhase("background")}>Send to background</button></div>`}
    ${session && phase !== "embedded" && html`<div role="status" class="notice quiet"><span><span class="mono" style="font-weight: 600">${session.name}</span> · ${session.agent.persona} · <span class="badge ${w ? "mark" : ""}">${w ? "waiting" : "running"}</span> in the background</span>
      <button class="plain" onClick=${() => onPhase("embedded")}>Bring back</button></div>`}
    <${Err} text=${act.error} />
  </section>`;
}

// --- work: details --------------------------------------------------------------------
function Labels({ repo, number, labels, editable, onChanged }) {
  const [adding, setAdding] = useState(false);
  const [value, setValue] = useState("");
  const act = useAct(onChanged);
  const change = (body) => act.run(() => post(`issues/${repo}/${number}/labels`, body));
  return html`<div class="labels">
    ${labels.map((l) => html`<span class="label" style=${editable ? "" : "padding-right: 8px"}>${l.name}
      ${editable && html`<button aria-label="Remove label ${l.name}" disabled=${act.busy} onClick=${() => change({ remove: [l.name] })}>
        <svg width="12" height="12" viewBox="0 0 12 12" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M3 3l6 6M9 3l-6 6" /></svg></button>`}</span>`)}
    ${editable && !adding && html`<button class="addlabel" onClick=${() => setAdding(true)}>+ label</button>`}
    ${adding && html`<form class="row" onSubmit=${async (e) => { e.preventDefault(); await change({ add: [value] }); setValue(""); setAdding(false); }}>
      <input aria-label="New label" autofocus style="min-height: 32px" value=${value} onInput=${(e) => setValue(e.target.value)} /></form>`}
    <${Err} text=${act.error} /></div>`;
}

function Comments({ list }) {
  return list.map((c) => html`<article class="body">
    <span class="row small soft" style="gap: 8px"><span class="mono" style="font-size: 12.5px">${c.author && c.author.login} · ${ago(c.createdAt || c.submittedAt)}</span>
      ${c.badge && html`<span class="badge dim">${c.badge}</span>`}</span><${Md} text=${c.body} /></article>`);
}

// One item, on its own page: what it is, what you can do, Claude, then its sections and details.
function ItemFrame({ kindLabel, where, title, state, stateCls, meta, actions, claude, sections, details }) {
  const [tab, setTab] = useState(sections[0].id);
  const current = sections.find((x) => x.id === tab) || sections[0];
  return html`<div class="stack" style="gap: 8px"><${Eyebrow} soft>${kindLabel} · GlassineOS/${where}<//>
      <h1 class="itemtitle">${title}</h1>
      <div class="row small soft" style="gap: 6px 14px"><span class="badge ${stateCls}">${state}</span>${meta.filter(Boolean).map((m) => html`<span>${m}</span>`)}</div></div>
    ${actions}
    ${claude}
    <div class="columns near"><section class="wide stack" aria-label="Content" style="gap: 16px">
        <div role="tablist" aria-label="Item sections" class="tabs">${sections.map((x) => html`<button role="tab" aria-selected=${current.id === x.id ? "true" : "false"} onClick=${() => setTab(x.id)}>${x.label}</button>`)}</div>
        ${current.body}</section>
      <aside class="aside stack itemside" aria-label="Details">${details}</aside></div>`;
}

function Comment({ busy, onSend, object, repo, number }) {
  const [text, setText] = useState("");
  const [note, setNote] = useState("");
  const draft = useAct();
  const ask = (kind) => draft.run(async () => {
    setNote("Drafting with claude -p, read-only…");
    try {
      const r = await post("agents/draft", { kind, object, repo, number });
      setText((t) => (t.trim() ? `${t.trim()}\n\n${r.text}` : r.text));
      setNote("Draft ready. Edit it, then Comment: nothing is posted until you do.");
    } catch (e) { setNote(""); throw e; }
  });
  return html`<label class="field" style="gap: 6px"><span>Comment</span>
    <textarea rows="4" placeholder="Markdown supported" value=${text} onInput=${(e) => setText(e.target.value)}></textarea></label>
    <${Err} text=${draft.error} />
    <div class="row"><button class="primary" disabled=${busy || !text.trim()} onClick=${async () => { await onSend(text); setText(""); setNote(""); }}>Comment</button>
      <button disabled=${draft.busy} onClick=${() => ask("comment")}><${TermIcon} />Draft with Claude</button>
      <button disabled=${draft.busy} onClick=${() => ask("summary")}><${TermIcon} />Summarise thread</button>
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

function Threads({ threads, base, repo, number, picked, setPicked, onChanged }) {
  const open = threads.filter((t) => !t.resolved);
  const ticked = open.filter((t) => picked.has(t.id));
  const all = open.length > 0 && ticked.length === open.length;
  const [showDone, setShowDone] = useState(false);
  const done = threads.filter((t) => t.resolved);
  const toggle = (id) => setPicked((p) => { const n = new Set(p); if (!n.delete(id)) n.add(id); return n; });
  return html`${open.length > 0 && html`<div class="notice"><span class="grow" style="font-weight: 600">${count(open.length, "open review thread")}${ticked.length ? ` · ${ticked.length} ticked, pinned for the agent` : " · tick the ones an agent should address"}</span>
      <button class="plain" onClick=${() => setPicked(all ? new Set() : new Set(open.map((t) => t.id)))}>${all ? "Clear selection" : "Select all"}</button></div>`}
    ${open.map((t) => html`<${Thread} key=${t.id} thread=${t} base=${base} repo=${repo} number=${number} ticked=${picked.has(t.id)} onTick=${() => toggle(t.id)} onChanged=${onChanged} />`)}
    ${done.length > 0 && html`<button class="link" style="align-self: flex-start" aria-expanded=${showDone ? "true" : "false"} onClick=${() => setShowDone(!showDone)}>${showDone ? "Hide" : "Show"} ${count(done.length, "resolved thread")}</button>`}
    ${showDone && done.map((t) => html`<${Thread} key=${t.id} thread=${t} base=${base} repo=${repo} number=${number} onChanged=${onChanged} />`)}`;
}

function IssueDetail({ repo, number, spawn, onChanged }) {
  const { data, error, reload } = useLoad(() => api(`issues/${repo}/${number}`), [repo, number]);
  const [confirm, dialog] = useConfirm();
  const act = useAct(async () => { await reload(); onChanged(); });
  if (error) return html`<${Err} text=${error} />`;
  if (!data) return html`<p class="soft">Loading…</p>`;
  const open = data.state === "OPEN";
  const conversation = html`<div class="body"><${Md} text=${data.body} /></div>
    <${Comments} list=${data.comments} />
    <${Comment} busy=${act.busy} object="issue" repo=${repo} number=${number} onSend=${(body) => act.run(() => post(`issues/${repo}/${number}/comment`, { body }))} />`;
  return html`${dialog}<${ItemFrame} kindLabel="Issue" where=${`${repo}#${number}`} title=${data.title}
    state=${data.state} stateCls=${open ? "" : "dim"}
    meta=${[`opened by ${data.author && data.author.login} ${ago(data.createdAt)}`, (data.assignees || []).length ? "" : "no assignee", count(data.comments.length, "comment")]}
    actions=${html`<${Err} text=${act.error} /><div class="row">
      <button disabled=${act.busy} onClick=${() => act.run(() => post("project/add", { repo, number }))}>Add to roadmap</button>
      ${open ? html`<button disabled=${act.busy} onClick=${() => confirm(
        { title: "Close this issue?", text: `${repo}#${number}: ${data.title}`, label: "Close issue", danger: true },
        () => act.run(() => post(`issues/${repo}/${number}/close`, { reason: "completed" })),
      )}>Close</button>` : html`<button class="primary" disabled=${act.busy} onClick=${() => act.run(() => post(`issues/${repo}/${number}/reopen`))}>Reopen</button>`}</div>`}
    claude=${html`<button class="nw-open" onClick=${() => planWork({ repo, context: `${repo}#${number}`, pins: [{ kind: "ref", label: `${repo}#${number}` }] })}>＋ New work from this…</button>${open && spawn({ kind: "issue", failing: false })}`}
    sections=${[{ id: "talk", label: "Conversation", body: conversation }]}
    details=${html`<dl class="defs"><dt>Assignee</dt><dd>${(data.assignees || []).map((a) => a.login).join(", ") || "unassigned"}</dd>
        <dt>On GitHub</dt><dd><a href=${data.url} target="_blank" rel="noreferrer noopener">${repo}#${number}</a></dd></dl>
      <${Labels} repo=${repo} number=${number} labels=${data.labels} editable=${true} onChanged=${reload} />`} />`;
}

const CHECK_BADGE = (s) => (["failure", "error", "timed_out", "cancelled", "action_required", "startup_failure"].includes(s) ? ["fail", "bad"]
  : ["success", "skipped", "neutral", "completed"].includes(s) ? [s === "skipped" ? "skip" : "ok", ""] : ["run", "dim"]);
const CheckRow = ({ name, state, note }) => {
  const [word, cls] = CHECK_BADGE(state);
  return html`<div class="checkrow"><span class="badge ${cls}">${word}</span><span class="n">${name}</span>${note && html`<span class="soft" style="font-size: 12.5px">${note}</span>`}</div>`;
};

function PrDetail({ repo, number, spawn, onChanged }) {
  const { data, error, reload } = useLoad(() => api(`prs/${repo}/${number}`), [repo, number]);
  const [method, setMethod] = useState("squash");
  const [diff, setDiff] = useState(null);
  const threads = useLoad(() => api(`prs/${repo}/${number}/threads`), [repo, number]);
  const [picked, setPicked] = useState(new Set());
  const [confirm, dialog] = useConfirm();
  const act = useAct(async () => { await reload(); onChanged(); });
  if (error) return html`<${Err} text=${error} />`;
  if (!data) return html`<p class="soft">Loading…</p>`;
  const open = data.state === "OPEN";
  const base = `prs/${repo}/${number}`;
  const openThreads = (threads.data || []).filter((t) => !t.resolved);
  const threadPins = openThreads.filter((t) => picked.has(t.id)).map((t) => ({ kind: "thread", label: `${t.path}${t.line ? `:${t.line}` : ""} (${t.id})` }));
  const merge = () => confirm(
    { title: "Merge this pull request?", text: `${repo}#${number} at ${(data.headRefOid || "").slice(0, 12)} into ${data.baseRefName} (${method}). Checks: ${data.checks}. If it has moved on from that commit, the merge fails.`, label: "Merge", danger: data.checks !== "passing" },
    () => act.run(() => post(`${base}/merge`, { method, head: data.headRefOid })),
  );
  // A push and a pull request event each report the same check.
  const checks = [...new Map(data.check_list.map((c) => [`${c.workflow}/${c.name}/${c.state}`, c])).values()];
  const passed = checks.filter((c) => ["success", "skipped", "neutral"].includes(c.state)).length;
  const reviews = (data.reviews || []).filter((r) => r.body || r.state !== "COMMENTED").map((r) => ({ ...r, badge: `review · ${String(r.state).toLowerCase().replaceAll("_", " ")}` }));
  const talk = [...data.comments, ...reviews].sort((a, b) => new Date(a.createdAt || a.submittedAt) - new Date(b.createdAt || b.submittedAt));
  const conversation = html`<div class="body"><${Md} text=${data.body} /></div>
    <${Comments} list=${talk} />
    ${threads.data && threads.data.length > 0 && html`<${Threads} threads=${threads.data} base=${base} repo=${repo} number=${number} picked=${picked} setPicked=${setPicked} onChanged=${threads.reload} />`}
    <${Err} text=${threads.error} />
    <${Comment} busy=${act.busy} object="pr" repo=${repo} number=${number} onSend=${(body) => act.run(() => post(`${base}/comment`, { body }))} />`;
  const checkList = html`<div class="stack" style="gap: 4px"><span class="small soft">${passed} of ${checks.length} passed</span>
    ${checks.map((c) => html`<${CheckRow} name=${c.workflow && c.workflow !== c.name ? `${c.workflow} · ${c.name}` : c.name} state=${c.state} />`)}
    ${!checks.length && html`<p class="soft">No checks on this pull request.</p>`}</div>`;
  const files = html`<div class="stack" style="gap: 4px">
    ${data.files.map((f) => html`<div class="checkrow"><span class="n">${f.path}</span><span>+${f.additions} −${f.deletions}</span></div>`)}
    <div class="row" style="margin-top: 8px"><button disabled=${act.busy} onClick=${() => act.run(async () => setDiff(diff === null ? await api(`${base}/diff`) : null))}>${diff === null ? "View diff" : "Hide diff"}</button></div>
    ${diff !== null && html`<div class="log">${diff}</div>`}</div>`;
  return html`${dialog}<${ItemFrame} kindLabel="Pull request" where=${`${repo}#${number}`} title=${data.title}
    state=${data.isDraft && open ? "DRAFT" : data.state} stateCls=${open ? (data.checks === "failing" ? "bad" : "") : "dim"}
    meta=${[`${data.headRefName} → ${data.baseRefName}`, `opened by ${data.author && data.author.login} ${ago(data.createdAt)}`, `+${data.additions} −${data.deletions}`]}
    actions=${html`<${Err} text=${act.error} />${open && html`<div class="row">
      ${!data.isDraft && html`<button class="primary" disabled=${act.busy} onClick=${merge}>Merge…</button>
        <select aria-label="Merge method" value=${method} onChange=${(e) => setMethod(e.target.value)}>
          <option value="squash">Squash</option><option value="merge">Merge commit</option><option value="rebase">Rebase</option></select>`}
      ${data.isDraft && html`<button class="primary" disabled=${act.busy} onClick=${() => act.run(() => post(`${base}/ready`))}>Mark ready</button>`}
      <button disabled=${act.busy} onClick=${() => act.run(() => post(`${base}/update-branch`))}>Update branch</button>
      <button class="danger" disabled=${act.busy} onClick=${() => confirm(
        { title: "Close without merging?", text: `${repo}#${number}: ${data.title}`, label: "Close pull request", danger: true },
        () => act.run(() => post(`${base}/close`)),
      )}>Close</button></div>`}`}
    claude=${html`<button class="nw-open" onClick=${() => planWork({ repo, context: `${repo}#${number}`, pins: [{ kind: "ref", label: `${repo}#${number}` }] })}>＋ New work from this…</button>${open && spawn({ kind: "pr", failing: data.checks === "failing", threads: { open: openThreads.length, pins: threadPins, reviews: reviews.filter((r) => r.body && r.state !== "APPROVED").length } })}`}
    sections=${[{ id: "talk", label: "Conversation", body: conversation }, { id: "checks", label: `Checks ${checks.length}`, body: checkList }, { id: "files", label: `Files ${data.files.length}`, body: files }]}
    details=${html`<dl class="defs"><dt>Reviews</dt><dd>${(data.reviewDecision || "none").toLowerCase().replaceAll("_", " ")}</dd>
        <dt>State</dt><dd>${data.isDraft ? "draft · " : ""}${data.state.toLowerCase()} · ${String(data.mergeStateStatus || "").toLowerCase()}</dd>
        <dt>On GitHub</dt><dd><a href=${data.url} target="_blank" rel="noreferrer noopener">${repo}#${number}</a></dd></dl>
      ${data.labels.length > 0 && html`<${Labels} repo=${repo} number=${number} labels=${data.labels} editable=${false} />`}`} />`;
}

function duration(job) {
  if (!job.startedAt || !job.completedAt) return "";
  const s = Math.round((new Date(job.completedAt) - new Date(job.startedAt)) / 1000);
  return s < 0 ? "" : s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

function RunDetail({ repo, id, spawn, onChanged }) {
  const { data, error, reload } = useLoad(() => api(`runs/${repo}/${id}`), [repo, id], 20000);
  const [log, setLog] = useState(null);
  const act = useAct(async () => { await reload(); onChanged(); });
  const logs = useAct();
  if (error) return html`<${Err} text=${error} />`;
  if (!data) return html`<p class="soft">Loading…</p>`;
  const running = data.status !== "completed";
  const failed = data.conclusion === "failure";
  const show = (all) => logs.run(async () => setLog(await api(`runs/${repo}/${id}/log${all ? "?all=1" : ""}`)));
  const jobs = data.jobs || [];
  const failedJobs = jobs.filter((j) => j.conclusion === "failure");
  const summary = html`${failedJobs.length > 0 && html`<p style="font-weight: 600; overflow-wrap: anywhere">Failed: ${failedJobs.map((j) => j.name).join(", ")}</p>`}
    <${Err} text=${logs.error} /><div class="row">
      <button disabled=${logs.busy} onClick=${() => show(false)}>Failed steps log</button>
      <button disabled=${logs.busy} onClick=${() => show(true)}>Full log</button></div>
    ${log !== null ? html`<div class="log">${log || "(empty: no failed steps)"}</div>` : html`<p class="small soft">Open a log to read it here.</p>`}`;
  const steps = html`<div class="stack" style="gap: 4px">${jobs.map((j) => html`<${CheckRow} name=${j.name} state=${j.conclusion || j.status} note=${duration(j)} />`)}</div>`;
  return html`<${ItemFrame} kindLabel="Workflow run" where=${`${repo} run ${id}`} title=${`${data.workflowName} · ${data.displayTitle}`}
    state=${String(data.conclusion || data.status).toUpperCase()} stateCls=${failed ? "bad" : running ? "dim" : ""}
    meta=${[`${data.event} on ${data.headBranch}`, (data.headSha || "").slice(0, 7), ago(data.createdAt)]}
    actions=${html`<${Err} text=${act.error} /><div class="row">
      ${running ? html`<button class="primary" disabled=${act.busy} onClick=${() => act.run(() => post(`runs/${repo}/${id}/cancel`))}>Cancel</button>`
        : html`<button class="primary" disabled=${act.busy} onClick=${() => act.run(() => post(`runs/${repo}/${id}/rerun`, { failed_only: true }))}>Re-run failed jobs</button>
          <button disabled=${act.busy} onClick=${() => act.run(() => post(`runs/${repo}/${id}/rerun`, { failed_only: false }))}>Re-run all</button>`}</div>`}
    claude=${!running && spawn({ kind: "run", failing: failed })}
    sections=${[{ id: "talk", label: "Summary", body: summary }, ...(jobs.length ? [{ id: "steps", label: `Jobs ${jobs.length}`, body: steps }] : [])]}
    details=${html`<dl class="defs"><dt>Workflow</dt><dd>${data.workflowName}</dd>
      <dt>Trigger</dt><dd>${data.event} on ${data.headBranch}</dd>
      <dt>On GitHub</dt><dd><a href=${data.url} target="_blank" rel="noreferrer noopener">${repo} run ${id}</a></dd></dl>`} />`;
}

function NewIssue({ groups, initial, roadmap, onDone, onCancel }) {
  const [repo, setRepo] = useState(initial || "hub");
  const [onBoard, setOnBoard] = useState(Boolean(roadmap));
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const act = useAct();
  return html`<h2 id="h-item" style="font-size: 22px; font-weight: 600">New issue</h2>
    <label class="field"><span>Repository</span><${RepoSelect} value=${repo} onChange=${setRepo} groups=${groups} all=${false} /></label>
    <label class="field"><span>Title</span><input value=${title} onInput=${(e) => setTitle(e.target.value)} /></label>
    <label class="field"><span>Description</span><textarea rows="6" placeholder="Markdown supported" value=${body} onInput=${(e) => setBody(e.target.value)}></textarea></label>
    <label class="row small"><input type="checkbox" style="min-height: 0" checked=${onBoard} onChange=${(e) => setOnBoard(e.target.checked)} /> Add to the roadmap</label>
    <${Err} text=${act.error} />
    <div class="row"><button class="primary" disabled=${act.busy || !title.trim()}
      onClick=${async () => { const r = await act.run(() => post(`issues/${repo}`, { title, body, roadmap: onBoard })); if (r) onDone(r); }}>Create</button>
      <button onClick=${onCancel}>Cancel</button></div>`;
}

function Dispatch({ repo, onDone, onCancel }) {
  const { data, error } = useLoad(() => api(`workflows/${repo}`), [repo]);
  const [file, setFile] = useState("");
  const [ref, setRef] = useState("main");
  const [confirm, dialog] = useConfirm();
  const act = useAct(onDone);
  const active = (data || []).filter((w) => w.state === "active");
  return html`${dialog}<h2 id="h-item" style="font-size: 22px; font-weight: 600">Run a workflow of ${repo}</h2>
    <${Err} text=${error || act.error} />
    <label class="field"><span>Workflow</span><select value=${file} onChange=${(e) => setFile(e.target.value)}>
      <option value="">Choose…</option>${active.map((w) => html`<option value=${w.path.split("/").pop()}>${w.name}</option>`)}</select></label>
    <label class="field"><span>Branch</span><input value=${ref} onInput=${(e) => setRef(e.target.value)} /></label>
    <div class="row"><button class="primary" disabled=${!file || act.busy} onClick=${() => confirm(
      { title: "Start this workflow?", text: `${file} of ${repo} on ${ref}. Some workflows publish things.`, label: "Start" },
      () => act.run(() => post(`workflows/${repo}/${file}/dispatch`, { ref })),
    )}>Start workflow</button><button onClick=${onCancel}>Cancel</button></div>`;
}

function RepoSelect({ value, onChange, groups, all = true }) {
  return html`<select value=${value || ""} onChange=${(e) => onChange(e.target.value)}>
    ${all && html`<option value="">All · by layer</option>`}
    ${groups.map((g) => html`<optgroup label=${g.title}>${g.repos.map((r) => html`<option value=${r.name}>${r.name}</option>`)}</optgroup>`)}
  </select>`;
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
    state: i.state, icon: i.state === "OPEN" ? "open" : "pass", at: i.updatedAt, object: "issue", labels: i.labels.map((l) => l.name), startable: i.state === "OPEN",
  }),
  prs: (p) => ({
    key: `${p.repo}#${p.number}`, repo: p.repo, number: p.number, ref: `${p.repo}#${p.number}`, title: p.title,
    sub: `${p.headRefName} → ${p.baseRefName}`, agent: p.headRefName.startsWith("agent/"), object: "pr", at: p.updatedAt, labels: p.labels.map((l) => l.name), startable: p.state === "OPEN",
    state: p.state !== "OPEN" ? p.state : p.isDraft ? "Draft" : p.checks === "failing" ? "Failing" : p.checks === "pending" ? "Checks" : p.checks === "passing" ? "Ready" : "Open",
    icon: p.state !== "OPEN" ? "pass" : p.checks === "failing" ? "fail" : p.checks === "pending" ? "run" : p.checks === "passing" ? "pass" : "open",
  }),
  actions: (r) => ({
    key: `${r.repo}/${r.databaseId}`, repo: r.repo, number: r.databaseId, ref: `${r.workflowName} ${r.databaseId}`, title: `${r.repo} · ${r.displayTitle}`,
    sub: `${r.event} on ${r.headBranch} · ${(r.headSha || "").slice(0, 7)}`, agent: (r.headBranch || "").startsWith("agent/"), object: "run", at: r.createdAt, labels: [], startable: r.status === "completed",
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

function WorkRow({ row, tab, scope, session, sessions, phase, action }) {
  const open = hash("work", { tab, repo: scope, at: row.repo, item: row.number });
  const kind = { issues: "issue", prs: "pr", actions: "run" }[tab];
  // Only a plain click: a link opened in a new tab is just the item.
  const planIt = (e) => { if (!e.ctrlKey && !e.metaKey && !e.shiftKey && !e.button) rowPlan = { key: `${kind}/${row.repo}/${row.number}`, action: action.id, title: action.title }; };
  return html`<div class="wrow">
    <span class="ic"><${StateIcon} kind=${row.icon} /></span>
    <a class="t" href=${open}><span class="line"><span class="mono soft ref">${row.ref}</span><b>${row.title}</b></span><span class="small soft sub">${row.sub}</span></a>
    ${session && html`<a class="sesschip" href=${open}><${TermIcon} />${sessions.length > 1 ? `${sessions.length} sessions · ${sessions.map((x) => x.name).join(", ")}`
      : `${session.name}${(session.agent.also_numbers || []).length ? (String(session.agent.number) === String(row.number) ? " · primary" : " · also covers") : ""} · ${session.agent.waiting ? "waiting" : phase === "embedded" ? "running" : "background"}`}</a>`}
    <span class="state">${row.state}</span><span class="age">${age(row.at)}</span>
    ${action && html`<a class="button start" title=${`${action.summary} The planner runs first; you confirm its spec. ${action.ceiling}`} href=${open} onClick=${planIt}><${TermIcon} />${action.title}</a>`}
  </div>`;
}

// Work's tabs. The queue is its own view of the pull requests, so it has the page to itself.
function Work({ query }) {
  return query.tab === "queue" ? html`<${WorkQueue} />` : html`<${WorkLists} query=${query} />`;
}

function WorkLists({ query }) {
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
  const [phases, setPhases] = useState({}); // session name → embedded, or background when absent
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
  const sessionsOf = (row) => list.filter((s) => s.agent && s.agent.object === row.object && s.agent.repo === row.repo && (String(s.agent.number) === String(row.number) || (s.agent.also_numbers || []).some((n) => String(n) === String(row.number))));
  const sessionOf = (row) => sessionsOf(row)[0];
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
    const session = sessionOf(current);
    const embedded = session && phases[session.name] === "embedded";
    const spawn = ({ kind, failing, threads }) => html`<${Spawn} key=${current.key} kind=${kind} repo=${current.repo} number=${current.number} failing=${failing} threads=${threads}
        session=${session} phase=${session ? phases[session.name] : null}
        onStarted=${async (r) => { setPhases((p) => ({ ...p, [r.name]: "embedded" })); await sessions.reload(); }}
        onPhase=${(ph) => session && setPhases((p) => ({ ...p, [session.name]: ph }))} />
      ${embedded && html`<section class="embedded" aria-labelledby="h-emb">
        <div class="termhead"><h2 id="h-emb">${session.name}</h2>
          <span class="badge ${session.agent.waiting ? "mark" : ""}">${session.agent.waiting ? "waiting" : "running"}</span>
          <span class="small soft" style="flex: 1 1 260px">${session.agent.persona} · <span class="mono">${session.agent.model}</span></span>
          <button class="plain" onClick=${() => setPhases((p) => ({ ...p, [session.name]: "background" }))}>Send to background</button>
          <a class="button plain" href=${hash("shells", { name: session.name })}>Open in Sessions</a></div>
        <${TerminalView} key=${session.name} name=${session.name} onGone=${() => sessions.reload()} /></section>`}`;
    const props = { key: current.key, repo: current.repo, spawn, onChanged: reload };
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
      <button onClick=${() => planWork({ repo: repo || undefined })}>${repo ? `＋ New in ${repo}…` : "＋ New work…"}</button>
      <button class="primary" disabled=${tab === "actions" && !repo} title=${tab === "actions" && !repo ? "Choose a repository first" : ""} onClick=${() => setPanel(tab === "actions" ? "dispatch" : "new")}>${tab === "actions" ? "Run workflow…" : repo ? `New issue in ${repo}` : "New issue"}</button></div>
    <p style="font-size: 17px; line-height: 1.4"><span class="mono" style="font-weight: 600">${repo ? `GlassineOS/${repo}` : `GlassineOS · all ${groups.flatMap((g) => g.repos).length} repositories`}</span>
      <span class="soft"> · ${repo ? (layer || "") : groupBy === "needs" ? "grouped by what needs you" : "all"}</span></p>
    ${panel && html`<div class="panel">${panel === "new" ? html`<${NewIssue} groups=${groups} initial=${repo || query.repo} roadmap=${query.roadmap === "1"} onCancel=${() => setPanel(null)}
        onDone=${(r) => { setPanel(null); reload(); setNotice(r.roadmap_error ? `Created, but not added to the roadmap: ${r.roadmap_error}` : null); go({ at: r.repo, item: r.number, new: undefined, roadmap: undefined }); }} />`
      : html`<${Dispatch} key=${repo} repo=${repo} onCancel=${() => setPanel(null)} onDone=${() => { setPanel(null); reload(); }} />`}</div>`}
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
      <div class="wlist">${group.map((r) => { const s = sessionOf(r); return html`<${WorkRow} key=${r.key} row=${r} tab=${tab} scope=${scope} session=${s} sessions=${sessionsOf(r)} phase=${s ? phases[s.name] : null} action=${startFor(r)} />`; })}</div></section>`)}
    ${data && !rows.length && html`<p class="soft">Nothing here.</p>`}
    ${!data && loading && html`<p class="soft">Loading…</p>`}
    ${rows.length > 0 && html`<p class="small soft">Open an item to work on it full width, and k / j steps through this list from there. The button on a row plans its most likely Claude action.</p>`}
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

function DocsTabs({ tab }) {
  return html`<div role="tablist" aria-label="Docs" class="tabs">
    <a role="tab" aria-selected=${tab === "docs" ? "true" : "false"} href=${hash("docs")}>Docs</a>
    <a role="tab" aria-selected=${tab === "notes" ? "true" : "false"} href=${hash("docs", { tab: "notes" })}>Notes</a></div>`;
}

function Docs({ query }) {
  return query.tab === "notes" ? html`<${NotesPage} />` : html`<${DocsSearch} />`;
}

function DocsSearch() {
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
      <${DocsTabs} tab="docs" />
      <div class="stack tight"><${Eyebrow} soft>docs.glassine.org · search by meaning<//><h1 id="h-search">Docs</h1></div>
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
function TerminalView({ name, onGone, focusRef, quiet }) {
  const box = useRef();
  const [note, setNote] = useState("Connecting…");
  const [copied, setCopied] = useState("");
  const [typing, setTyping] = useState(true);
  useEffect(() => {
    const term = new Terminal({
      cursorBlink: true, fontFamily: '"IBM Plex Mono", ui-monospace, monospace', fontSize: 14, scrollback: 5000,
      theme: { background: "#121212", foreground: "#eeeeee", cursor: "#eeeeee" },
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
function NewShell({ initial, onDone, onCancel }) {
  const [name, setName] = useState(initial || "");
  const [cwd, setCwd] = useState("");
  const [command, setCommand] = useState("");
  const act = useAct();
  return html`<div class="panel" style="padding: 14px; gap: 10px">
    <${Err} text=${act.error} />
    <label class="field"><span>Name</span><input value=${name} onInput=${(e) => setName(e.target.value)} /></label>
    <label class="field"><span>Directory</span><input placeholder="home" value=${cwd} onInput=${(e) => setCwd(e.target.value)} /></label>
    <label class="field"><span>Command</span><input placeholder="your shell" value=${command} onInput=${(e) => setCommand(e.target.value)} /></label>
    <div class="row"><button class="primary" disabled=${act.busy || !name.trim()} onClick=${async () => {
      const r = await act.run(() => post("shells", { name, cwd: cwd || null, command: command || null }));
      if (r) onDone(name);
    }}>Start</button><button onClick=${onCancel}>Cancel</button></div></div>`;
}

const shortModel = (m) => (m ? m[0].toUpperCase() + m.slice(1) : "");

function Manifest({ session, work }) {
  const a = session && session.agent;
  const { data, error } = useLoad(() => (a ? post("agents/manifest", { name: session.name }) : Promise.resolve(null)), [session && session.name]);
  const [show, setShow] = useState(false);
  if (!session) return html`<aside class="manifest panel"><h2 class="eyebrow">Session</h2><p class="small soft">Choose a session. They keep running on the host when you close this page.</p></aside>`;
  if (!a) {
    return html`<aside class="manifest panel" aria-labelledby="h-man"><h2 id="h-man" class="eyebrow">Plain shell</h2>
      <p style="font-size: 14.5px">A plain tmux shell as your user. No persona, no prompt; the tool server's URL and a token are in its environment, so a <code>claude</code> you start here can use the hub too.</p>
      <dl class="defs"><dt>Directory</dt><dd class="mono" style="font-size: 13px">${session.cwd}</dd><dt>Running</dt><dd class="mono" style="font-size: 13px">${session.command}</dd>
        <dt>Attach</dt><dd class="mono" style="font-size: 13px">tmux -L glassine-hub attach -t ${session.name}</dd></dl></aside>`;
  }
  const m = data && data.manifest;
  const tab = a.object === "pr" ? "prs" : a.object === "issue" ? "issues" : "actions";
  const closes = a.full && a.object === "issue" && a.number ? [a.number, ...(a.also_numbers || [])] : [];
  const suggested = work.items.find((i) => i.session === session.name && i.number);
  return html`<aside class="manifest panel" aria-labelledby="h-man">
    <div class="row" style="justify-content: space-between"><h2 id="h-man" class="eyebrow">Session manifest</h2>
      ${m && a.repo && a.number && html`<a class="small" href=${hash("launch", { action: a.action, repo: a.repo, number: a.number })} onClick=${() => { advancedHandoff = m.config; }}>Clone setup</a>`}</div>
    <${Err} text=${error} />
    <div class="persona"><i aria-hidden="true">${a.persona[0]}</i><span><b>${a.persona}</b><span class="mono soft" style="font-size: 12.5px; overflow-wrap: anywhere">${a.model} · ${a.effort}</span></span></div>
    <div class="stack tight"><h3 class="eyebrow">Prompt builder</h3><span style="font-size: 14px">${a.title} · ${whereFrom(a)}</span>
      ${m && m.config.docs_query && html`<span class="soft" style="font-size: 13px">${count(m.config.docs.length, "docs passage")} from “${m.config.docs_query}”</span>`}
      <button class="plain" aria-expanded=${show ? "true" : "false"} style="align-self: flex-start; min-height: 36px; border-radius: 10px" onClick=${() => setShow(!show)}>${show ? "Hide built prompt" : "Show built prompt"}</button>
      ${show && m && html`<pre class="shadow">${m.prompt}</pre>`}</div>
    ${m && html`<div class="stack tight"><h3 class="eyebrow">Skills</h3><div class="row" style="gap: 6px">${m.skills.map((s) => html`<span class="badge" style="text-transform: none; letter-spacing: 0; font-size: 12.5px">${s}</span>`)}</div></div>
      <div class="stack" style="gap: 4px"><h3 class="eyebrow">Tools${a.full ? "" : ` · ${m.config.tools.length + m.config.hub_tools.length}`}</h3>
        ${a.full ? html`<p class="small">Full Claude Code, with your rights.</p>`
          : [...m.config.hub_tools, ...m.config.tools].map((t) => html`<div class="tool-row"><span class="mono" style="font-size: 13px">${t}</span><span class="badge">allow</span></div>`)}
        <span class="soft" style="font-size: 12.5px; margin-top: 4px">${m.ceiling}</span></div>
      <dl class="defs" style="border-top: 1px dotted var(--ink); padding-top: 12px">
        <dt>Posts as</dt><dd class="mono" style="font-size: 13px">${a.posts_as || "you"}</dd>
        <dt>From</dt><dd>${suggested ? `${suggested.by === STEWARD ? "Steward" : suggested.by} suggestion · ` : ""}${a.repo && a.number ? html`<a href=${hash("work", { tab, repo: a.repo, item: a.number })}>${whereFrom(a)}</a>` : whereFrom(a)}</dd>
        ${(a.also_numbers || []).length > 0 && html`<dt>Covers</dt><dd class="mono" style="font-size: 13px">${a.repo}#${a.number} (primary), ${a.also_numbers.map((n) => `${a.repo}#${n}`).join(", ")}</dd>`}
        ${closes.length > 0 && html`<dt>PR will say</dt><dd class="mono" style="font-size: 13px">${closes.map((n) => `Closes #${n}`).join(" · ")}</dd>`}
        ${m.checkouts.map((c) => html`<dt>Worktree</dt><dd class="mono" style="font-size: 13px; overflow-wrap: anywhere">${c}</dd>`)}
        <dt>Attach</dt><dd class="mono" style="font-size: 13px">tmux -L glassine-hub attach -t ${session.name}</dd></dl>`}
  </aside>`;
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
const planWork = (opts = {}) => window.dispatchEvent(new CustomEvent("hub-new-work", { detail: opts }));
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
const startForm = (item) => window.dispatchEvent(new CustomEvent("hub-start-form", { detail: item }));
const nwWaits = (item) => NW_WAITING.includes(item.state);

const PlannerModel = ({ value, onChange, id }) => html`<div class="stack" style="gap: 6px"><span id=${id} class="eyebrow">Planner</span>
  <div role="radiogroup" aria-labelledby=${id} class="seg">${PLANNER_CHOICES.map((m) => html`<button role="radio" aria-checked=${value === m ? "true" : "false"} onClick=${() => onChange(m)}>${NW_MODEL[m]}</button>`)}</div></div>`;

const NW_STAGES = ["config", "review", "session", "drafts"];

function NewWork({ open, work, asks, onClose, reload }) {
  const ref = useRef();
  const [id, setId] = useState(open.id || null);
  const live = id ? work.items.find((i) => i.id === id) : null;
  const seed = useRef(live || open).current;
  const [action, setAction] = useState(seed.action || (work.templates[0] && work.templates[0].id));
  const template = work.templates.find((t) => t.id === action) || work.templates[0];
  const [repo, setRepo] = useState(seed.repo || null);
  const [describe, setDescribe] = useState(seed.describe || "");
  const [paths, setPaths] = useState(seed.paths || "");
  const [notes, setNotes] = useState(seed.notes || "");
  const [pins, setPins] = useState(seed.pins || []);
  const [pinning, setPinning] = useState(null);
  const [plannerModel, setPlannerModel] = useState(seed.planner_model || PLANNER_DEFAULT);
  const [driver, setDriver] = useState(seed.driver || (open.by === STEWARD ? "steward" : "you"));
  const [editing, setEditing] = useState(false); // back on the form, with a plan still waiting
  const [model, setModel] = useState(null); // yours, once you've chosen on the plan
  const [brief, setBrief] = useState(null);
  const [preview, setPreview] = useState(null);
  const [picked, setPicked] = useState({});
  const [note, setNote] = useState(null);
  const act = useAct(reload);
  const { data: overview, error: overviewError } = useLoad(() => api("overview"), [], 20000);
  useEffect(() => { ref.current.showModal(); }, []);
  const planned = live && live.state === "planned";
  const spec = live && live.spec;
  const pick = live && template && template.models.includes(live.planner_pick) ? live.planner_pick : live && live.model;
  const chosenModel = model || pick;
  const shownBrief = brief === null ? (spec && spec.brief) || "" : brief;
  useEffect(() => {
    if (!planned || editing || !spec) return undefined;
    const timer = setTimeout(() => { post("agents/preview", { config: { ...spec, model: chosenModel, brief: shownBrief } }).then(setPreview).catch(() => setPreview(null)); }, 250);
    return () => clearTimeout(timer);
  }, [planned, editing, chosenModel, shownBrief]);
  if (!template) return html`<dialog ref=${ref} onClose=${() => onClose()}><p>No kinds of new work are set up on this hub.</p><button onClick=${() => onClose()}>Close</button></dialog>`;
  const state = live ? live.state : "form";
  const text = NW_TEXT[template.id] || {};
  const fixedRepo = template.repo;
  const chosenRepo = fixedRepo || repo;
  const form = state === "form" || state === "offered" || (planned && editing);
  const started = ["starting", "running"].includes(state);
  const running = state === "planning" || started;
  const stage = form ? "config" : state === "planning" ? "planning" : planned ? "review" : started ? "session" : "drafts";
  const at = NW_STAGES.indexOf(stage === "planning" ? "review" : stage);
  const by = live ? live.by : open.by;
  const byAgent = by && by !== "you";
  const byName = by === STEWARD ? "The Steward" : by;
  const why = live ? live.why : open.why;
  const context = open.context || (live && live.context);
  const repos = overview ? overview.groups.flatMap((g) => g.repos.map((r) => r.name)) : [];
  const drafts = live ? live.drafts : [];
  const withSteward = drafts.filter((d) => d.state === "handed").length;
  const isOn = (_d, i) => picked[i] === true;  // yours to read first: nothing starts out chosen
  const chosen = drafts.flatMap((d, i) => (d.state === "draft" && isOn(d, i) ? [i] : []));
  const left = drafts.filter((d) => d.state === "draft").length;
  // true, false, or null when it isn't known: never read as private.
  const repoRow = (name) => (overview ? overview.groups.flatMap((g) => g.repos).find((r) => r.name === name) : null);
  const isPublic = (name) => { const r = repoRow(name); return r ? !r.private : null; };
  const targets = [...new Set(chosen.map((i) => drafts[i].target))];
  const publicCount = chosen.filter((i) => isPublic(drafts[i].target) === true).length;
  const unknown = targets.filter((t) => isPublic(t) === null);
  const fileLabel = `File ${chosen.length} in ${targets.join(", ")}${publicCount ? ` (${publicCount} public)` : ""}`;
  const filingNow = drafts.filter((d) => d.state === "filing").length;
  const session = live && live.session;
  const asking = session ? asks.open.filter((a) => a.session === session) : [];
  const plannerName = NW_MODEL[(live && live.planner_model) || plannerModel] || plannerModel;
  // What's still going keeps going: this leaves a way back to it.
  const close = () => onClose(id && running ? { id, name: session || template.title } : null);
  const runPlanner = () => act.run(async () => {
    setNote(null);
    const r = await post("new-work", { id: state === "offered" || planned ? id : null, action: template.id, repo: chosenRepo, describe: template.asks_describe ? describe : "", paths: template.asks_paths ? paths : "", notes, pins, model: seed.model || null, driver, why, context, planner_model: plannerModel });
    setId(r.work.id); setEditing(false); setModel(null); setBrief(null); setPreview(null);
  });
  const startSession = () => act.run(() => post(`new-work/${id}/approve`, { model: chosenModel, brief: shownBrief }));
  const file = () => act.run(async () => {
    const r = await post(`new-work/${id}/file`, { indexes: chosen });
    const filed = `${count(chosen.length - r.errors.length, "issue")} filed`;
    setNote(`${filed}${r.errors.length ? `, ${r.errors.length} not` : ""}${r.warnings.length ? `, ${r.warnings.length} not on the board` : ""}${r.errors.length || r.warnings.length ? ": see the draft." : "."}`);
  });
  const hand = () => act.run(async () => {
    await post(`new-work/${id}/hand`, { indexes: chosen });
    setNote(`${count(chosen.length, "draft")} with the Steward. Each issue it files asks you first.`);
  });
  const cancel = () => act.run(async () => { await post(`new-work/${id}/cancel`); onClose(); });
  const setAside = () => act.run(async () => { await post(`new-work/${id}/dismiss`); onClose(); });
  const addPin = () => { const v = (pinning || "").trim(); if (v) setPins([...pins, { kind: pinKind(v), label: v }]); setPinning(null); };
  const filing = driver === "steward"
    ? { label: `Send ${chosen.length} to the Steward`, held: false, run: hand, other: chosen.length ? `${fileLabel} myself instead` : "File them myself instead", otherHeld: unknown.length > 0, then: file }
    : { label: chosen.length ? fileLabel : "Choose drafts to file", held: unknown.length > 0, run: file, other: "Send to the Steward instead", otherHeld: false, then: hand };
  const status = form ? `The planner (${plannerName}) writes a spec first. Nothing runs until you approve it.`
    : state === "planning" ? "The planner is reading, read-only. You can send this to the background."
    : planned ? "Starting opens a real Claude session in tmux."
    : state === "starting" ? "Starting the session…"
    : state === "running" ? (asking.length ? "The session is waiting for your answer above." : "You can leave: send it to the background and the drafts land in Sessions › Needs you.")
    : filingNow ? `Filing ${count(filingNow, "draft")}…`
    : state === "done" && unknown.length ? `Filing waits: can't tell whether ${unknown.join(", ")} is public${overviewError ? ` (${overviewError})` : ""}. Trying again.`
    : state === "done" ? (left ? `${count(drafts.length, "draft")} ready. Nothing is filed yet.` : "Every draft has gone where you sent it.")
    : state === "failed" ? "Nothing was filed."
    : state === "filed" ? "Every draft has gone where you sent it."
    : state === "dismissed" ? `Set aside.${drafts.some((d) => d.state === "filed") ? "" : " Nothing was filed."}${withSteward ? ` The Steward still has ${withSteward}.` : ""}`
    : "";
  const steps = [
    ["config", "Configure", `${template.title} · ${chosenRepo || "choose a repository"}`],
    ["review", "Review the plan", at < 1 ? `planner ${plannerName} writes a spec` : stage === "planning" ? "planner running…" : stage === "review" ? "waiting for you" : `approved · ${NW_MODEL[live && live.model] || (live && live.model)}`],
    ["session", "Session", at < 2 ? `${template.persona}` : started ? (asking.length ? "asks you something" : state === "starting" ? "starting…" : "running") : session ? "finished" : "didn't run"],
    ["drafts", "Drafts", at < 3 ? "land here, or in Needs you" : left ? `${left} to review` : drafts.length ? "all sent" : "none"],
  ];
  const canGo = (step) => planned && ((step === "config" && !editing) || (step === "review" && editing));
  return html`<dialog ref=${ref} class="nw" aria-labelledby="nw-h" onClose=${close}>
    <div class="nw-head ${byAgent ? "agent" : ""}">
      ${by === STEWARD && html`<span class="ask-avatar steward-mark" aria-hidden="true">S</span>`}
      <h2 id="nw-h">${byAgent ? `${byName} drafted new work` : "Plan new work"}</h2>
      ${context && html`<span class="label mono" style="padding-right: 8px">from ${context}</span>`}
      <span style="flex: 1"></span>
      ${running && html`<button class="plain" onClick=${close}>Send to background</button>`}
      <button class="square" aria-label="Close" onClick=${close}>×</button></div>
    <div class="nw-stages">
      <nav class="nw-rail" aria-label="Stages"><ol>
        ${steps.map(([step, name, sub], i) => {
          const current = NW_STAGES[at] === step;
          return html`<li><button class="nw-step" disabled=${!canGo(step)} aria-current=${current ? "step" : null} onClick=${() => setEditing(step === "config")}>
            <span class="nw-n ${i < at ? "done" : ""}" aria-hidden="true">${i < at ? "✓" : i + 1}</span>
            <span class="stack" style="gap: 0; min-width: 0"><b>${name}</b><span class="small soft">${sub}</span></span></button></li>`;
        })}</ol>
        <p class="small soft nw-railnote">${started ? "The session is real: it keeps running if you close this or send it to the background." : "Steps 1 and 2 are cheap and reversible. The session in step 3 is where the time goes."}</p></nav>
      <div class="nw-body">
        ${byAgent && why && (stage === "config" || stage === "review") && html`<div class="nw-why"><span class="nw-why-word">why</span><span>${why}</span></div>`}
        ${form && html`<div role="radiogroup" aria-label="What to create" class="row" style="gap: 6px">
          ${work.templates.map((t) => html`<button role="radio" class="pill" aria-checked=${t.id === template.id ? "true" : "false"} onClick=${() => setAction(t.id)}>${t.title} <span class="nw-where">${t.repo ? "HUB" : "REPO"}</span></button>`)}</div>
        <p class="soft" style="font-size: 14.5px">${template.summary}</p>
        ${fixedRepo
          ? html`<div class="small"><${Eyebrow}>In<//> <span class="mono">GlassineOS/${fixedRepo}</span> · org board</div>`
          : html`<div class="stack" style="gap: 6px"><span id="nw-repo" class="eyebrow">Repository</span>
              <div role="radiogroup" aria-labelledby="nw-repo" class="row" style="gap: 6px">${repos.map((r) => html`<button role="radio" class="pill mono" aria-checked=${repo === r ? "true" : "false"} onClick=${() => setRepo(r)}>${r}</button>`)}
                ${!overview && html`<span class="small soft">Loading repositories…</span>`}</div></div>`}
        ${template.asks_paths && html`<label class="nw-field">Scope <span class="nw-sub">optional · paths in the repository</span>
          <input class="mono" value=${paths} placeholder="the whole repository" onInput=${(e) => setPaths(e.target.value)} /></label>`}
        ${template.asks_describe && html`<label class="nw-field">${text.label || "What to plan"}
          <textarea rows="3" placeholder=${text.hold || ""} value=${describe} onInput=${(e) => setDescribe(e.target.value)} /></label>`}
        <label class="nw-field">${byAgent ? `Notes — ${by === STEWARD ? "the Steward" : by} wrote these; edit freely` : "Notes for the planner"} <span class="nw-sub">optional · goes into the planner’s prompt</span>
          <textarea rows="2" placeholder=${text.hint || ""} value=${notes} onInput=${(e) => setNotes(e.target.value)} /></label>
        <div class="row" style="gap: 6px"><span class="eyebrow">Pinned</span>
          ${pins.map((x, i) => html`<button class="label mono" style="padding-right: 8px" title="Remove this pin" onClick=${() => setPins(pins.filter((_, j) => j !== i))}>${x.label} ×</button>`)}
          ${pinning === null ? html`<button class="addlabel" onClick=${() => setPinning("")}>+ pin</button>`
            : html`<input class="mono" aria-label="What to pin: a reference, file, docs page or link" autofocus value=${pinning} onInput=${(e) => setPinning(e.target.value)} onBlur=${addPin} onKeyDown=${(e) => { if (e.key === "Enter") { e.preventDefault(); addPin(); } if (e.key === "Escape") { e.preventDefault(); setPinning(null); } }} />`}</div>
        <div class="row" style="gap: 14px 24px; align-items: flex-start">
          <${PlannerModel} id="nw-pm" value=${plannerModel} onChange=${setPlannerModel} />
          <div class="stack" style="gap: 6px"><span id="nw-drv" class="eyebrow">Drafts go to</span>
            <div role="radiogroup" aria-labelledby="nw-drv" class="seg">
              <button role="radio" aria-checked=${driver === "you" ? "true" : "false"} onClick=${() => setDriver("you")}>Me · I hand it off</button>
              <button role="radio" aria-checked=${driver === "steward" ? "true" : "false"} onClick=${() => setDriver("steward")}>The Steward · refines & dispatches</button></div>
            <span class="small soft" style="max-width: 46ch">${driver === "steward" ? "You still send them, and each issue it files asks you first." : "They wait for you here and in Needs you."}</span></div></div>`}
        ${stage === "planning" && html`<div role="status" class="stack" style="gap: 8px">
          <span class="row" style="font-weight: 600; font-size: 18px"><${StateIcon} kind="run" />The planner is writing the spec</span>
          <span class="mono soft" style="font-size: 12.5px">claude -p · ${plannerName} · read-only hub tools · up to a few minutes</span>
          <p class="small soft">Nothing runs yet. You review the spec before any session starts.</p></div>`}
        ${stage === "review" && spec && html`${live.error && html`<${Err} text=${`${live.error} The plan is still here: you can press Start again.`} />`}<div class="row" style="gap: 6px 12px; align-items: baseline"><h3>Review the plan</h3>
            <span class="small soft">written by the planner (${plannerName})${live.planner_cost_usd != null ? ` · $${live.planner_cost_usd.toFixed(2)}` : ""} · nothing has run yet</span></div>
          <div class="nw-review">
            <dl class="defs" style="flex: 999 1 320px; min-width: 0">
              ${live.notes && html`<dt>Your notes</dt><dd>${live.notes}</dd>`}
              ${spec.pins.length > 0 && html`<dt>Pinned</dt><dd>${spec.pins.map((x) => x.label).join(" · ")}</dd>`}
              <dt>Persona</dt><dd>${spec.persona}</dd>
              <dt>Effort</dt><dd>${spec.effort}</dd>
              ${preview && html`<dt>Worktree</dt><dd>${preview.worktree}</dd>`}
              <dt>Hub tools</dt><dd>${(spec.hub_tools || []).join(", ") || "none"}</dd>
              <dt>Tools</dt><dd>${(spec.tools || []).join(", ") || "none"}</dd></dl>
            <div class="stack" style="gap: 6px; flex: 1 1 260px"><span id="nw-am" class="eyebrow">Agent model</span>
              <div role="radiogroup" aria-labelledby="nw-am" class="seg" style="align-self: flex-start">${template.models.map((m) => html`<button role="radio" aria-checked=${chosenModel === m ? "true" : "false"} onClick=${() => setModel(m)}>${NW_MODEL[m] || m}</button>`)}</div>
              <span class="small soft">${chosenModel === pick ? `${NW_MODEL[chosenModel] || chosenModel}: the planner’s pick for this work.` : `${NW_MODEL[chosenModel] || chosenModel}: your choice. The planner suggested ${NW_MODEL[pick] || pick}.`}</span>
              <span class="small nw-ceiling">${template.ceiling}</span></div></div>
          ${spec.docs.length > 0 && html`<div class="stack tight"><${Eyebrow}>Context · docs search${spec.docs_query ? ` “${spec.docs_query}”` : ""}<//>
            <ul class="stack" style="gap: 4px">${spec.docs.map((d) => html`<li class="passage"><span><b>${d.link}</b><span class="soft" style="font-size: 13px">${d.why}</span></span></li>`)}</ul></div>`}
          <label class="nw-field">Briefing <span class="nw-sub">the planner wrote this; edit freely · goes into the first prompt</span>
            <textarea class="mono" rows="6" value=${shownBrief} onInput=${(e) => setBrief(e.target.value)} /></label>
          ${preview && html`<details><summary class="eyebrow" style="min-height: 32px; cursor: pointer">The whole first prompt</summary><pre class="shadow" style="margin-top: 4px">${preview.prompt}</pre></details>`}`}
        ${stage === "session" && html`<div class="row" style="gap: 8px 14px"><span class="mono" style="font-weight: 600">${session || template.title}</span>
            <span class="badge ${asking.length ? "mark" : ""}">${state === "starting" ? "starting" : asking.length ? "waiting" : "running"}</span>
            <span class="small soft" style="flex: 1">${template.persona} · ${NW_MODEL[live.model] || live.model}</span>
            ${session && html`<a class="button" href=${hash("shells", { tab: "all", name: session })} onClick=${close}>Open in Sessions</a>`}
            ${session && html`<button class="plain" disabled=${act.busy} title="Stops the turn" onClick=${() => act.run(() => post("agents/interrupt", { name: session }))}>Esc</button>`}</div>
          ${asking.map((a) => html`<${Ask} key=${a.id} ask=${a} compact onDone=${reload} />`)}
          ${session ? html`<div class="nw-term"><${TerminalView} key=${session} name=${session} quiet onGone=${reload} /></div>` : html`<p class="small soft">The session is on its way. This can take a moment while its checkout is made.</p>`}`}
        ${stage === "drafts" && html`<div class="row" style="gap: 6px 12px; align-items: baseline"><h3>Drafts</h3><span class="small soft" style="flex: 1">${session ? `from ${session}` : template.title} · Nothing is filed until you choose.</span><span class="mono small">${chosen.length} of ${left} selected</span></div>
          ${state === "failed" && html`<${Err} text=${live.error} />`}
          ${state === "dismissed" && drafts.length === 0 && html`<p class="small soft">Set aside before it wrote anything.</p>`}`}
      ${drafts.length > 0 && html`<div class="stack" style="gap: 10px">
        <div class="row" style="gap: 6px 12px; align-items: baseline"><h3>Drafts</h3><span class="small soft" style="flex: 1">Nothing is filed until you choose.</span><span class="mono small">${chosen.length} of ${left} selected</span></div>
        ${drafts.map((d, i) => {
          const on = d.state === "draft" && isOn(d, i);
          return html`<div class="nw-draft ${on ? "on" : ""}" key=${i}>
            ${d.state === "draft" && html`<input type="checkbox" aria-label=${`Select draft: ${d.title}`} checked=${on} onChange=${() => setPicked({ ...picked, [i]: !on })} />`}
            <div class="stack" style="gap: 4px; flex: 1; min-width: 0">
              <div class="row" style="gap: 6px 10px">
                ${d.severity && html`<span class="nw-sev ${d.severity}">${d.severity.toUpperCase()}</span>`}
                <strong>${d.title}</strong>
                ${d.state === "filed" && html`<a class="nw-tag" href=${d.url} target="_blank" rel="noreferrer">FILED</a>`}
                ${d.state === "handed" && html`<span class="nw-tag">WITH THE STEWARD</span>`}
                ${d.state === "filing" && html`<span class="nw-tag">FILING…</span>`}</div>
              ${d.body ? html`<div class="small nw-draft-body"><${Md} text=${d.body} showUrls=${true} /></div>` : html`<span class="small soft">No body</span>`}
              ${/!\[|<img|<\/?(?:picture|source|video|audio)\b/i.test(d.body) && html`<span class="small" role="alert">Has an image or media link: filing it can make GitHub fetch that address. Check it above.</span>`}
              <span class="small">→ <span class="mono">GlassineOS/${d.target}</span>${isPublic(d.target) === true && html` <span class="nw-tag">PUBLIC</span>`}${isPublic(d.target) === null && html` <span class="nw-tag">PUBLIC OR PRIVATE: NOT KNOWN YET</span>`}${d.labels.length > 0 && html` · <span class="mono">${d.labels.join(", ")}</span>`}${d.parent && html` · parent <span class="mono">${d.parent}</span>`}</span>
              ${d.note && html`<span class="small" role="alert">${d.note}</span>`}</div></div>`;
        })}</div>`}
        <${Err} text=${act.error} />
      </div>
    </div>
    <div class="nw-foot">
      ${form && html`<button class="primary" disabled=${act.busy || !chosenRepo || (template.asks_describe && !describe.trim())} title=${!chosenRepo ? "Choose a repository first" : ""} onClick=${runPlanner}>Run the planner</button>`}
      ${stage === "planning" && html`<button class="primary" disabled>Planning…</button>`}
      ${stage === "review" && html`<button class="primary" disabled=${act.busy} onClick=${startSession}>Start session</button>
        <button class="plain" disabled=${act.busy} onClick=${runPlanner}>Re-plan</button>
        <button class="plain" onClick=${() => setEditing(true)}>Back to configure</button>`}
      ${stage === "session" && html`<button class="primary" onClick=${close}>Send to background</button>`}
      ${state === "done" && left > 0 && html`<button class="primary" disabled=${act.busy || !chosen.length || filing.held} onClick=${filing.run}>${filing.label}</button>
        <button class="plain" disabled=${act.busy || !chosen.length || filing.otherHeld} onClick=${filing.then}>${filing.other}</button>`}
      ${state === "dismissed" && drafts.length > 0 && html`<button class="primary" disabled=${act.busy} onClick=${() => act.run(() => post(`new-work/${id}/bring_back`))}>Bring back</button>`}
      <span role="status" class="small" style="flex: 1 1 260px">${note || status}</span>
      ${running && html`<button class="plain" disabled=${act.busy || !id} onClick=${cancel}>${started ? "Stop session" : "Stop planner"}</button>`}
      ${(state === "offered" || planned || state === "failed" || (state === "done" && left > 0)) && html`<button class="plain" disabled=${act.busy} onClick=${setAside}>${state === "offered" ? "Not now" : "Set aside"}</button>`}
      ${((state === "done" && left > 0) || (state === "dismissed" && left > 0)) && html`<${Discard} item=${live} reload=${reload} onDone=${() => onClose()} />`}
      <button class="plain" onClick=${close}>${running ? "Close · keeps running" : form && state !== "offered" && !planned ? "Cancel" : "Close"}</button>
    </div></dialog>`;
}

// A session the Steward (or another session) suggested: yours to read and change, and nothing runs until you press Start.
function StartForm({ item, work, onClose, reload }) {
  const ref = useRef();
  const live = work.items.find((i) => i.id === item.id) || item;
  const state = live.state;
  const planned = state === "planned";
  const spec = live.spec;
  const [info, setInfo] = useState(null);
  const [config, setConfig] = useState(null);
  const [preview, setPreview] = useState(null);
  const [previewError, setPreviewError] = useState(null);
  const [titles, setTitles] = useState({});
  const [adding, setAdding] = useState("");
  const [plannerModel, setPlannerModel] = useState(live.planner_model || PLANNER_DEFAULT);
  const [editing, setEditing] = useState(false); // back on the form, with a plan still waiting
  const [model, setModel] = useState(null); // yours, once you've chosen on the plan
  const [brief, setBrief] = useState(null);
  const act = useAct(reload);
  useEffect(() => { ref.current.showModal(); }, []);
  useEffect(() => {
    act.run(async () => {
      const a = (await post("agents/action", { action: live.action })).action;
      const fresh = (await post("agents/defaults", { action: live.action, repo: live.repo, number: live.number })).config;
      setInfo(a);
      setConfig({ ...fresh, notes: live.notes || "", pins: live.pins || [], also_numbers: live.also_numbers || [] });
    });
  }, []);
  const form = state === "offered" || state === "failed" || (planned && editing);
  const review = planned && !editing;
  const pick = planned && info && info.models.includes(live.planner_pick) ? live.planner_pick : live.model;
  const chosenModel = model || pick;
  const shownBrief = brief === null ? (spec && spec.brief) || "" : brief;
  const covers = config ? [config.number, ...config.also_numbers] : [];
  const canAdd = info && info.object === "issue";
  useEffect(() => {
    if (!info) return;
    const path = info.object === "pr" ? "prs" : "issues";
    covers.filter((n) => !(n in titles)).forEach((n) => {
      api(`${path}/${live.repo}/${n}`).then((r) => setTitles((t) => ({ ...t, [n]: r.title }))).catch((e) => setTitles((t) => ({ ...t, [n]: `Can't read it: ${e.message}` })));
    });
  }, [info, covers.join()]);
  useEffect(() => {
    if (!config) return undefined;
    const shown = review && spec ? { ...spec, model: chosenModel, brief: shownBrief } : config;
    const timer = setTimeout(async () => {
      try { setPreview(await post("agents/preview", { config: shown })); setPreviewError(null); } catch (e) { setPreviewError(e.message); }
    }, 250);
    return () => clearTimeout(timer);
  }, [config, review, chosenModel, shownBrief]);
  const set = (patch) => setConfig((c) => ({ ...c, ...patch }));
  const makePrimary = (n) => set({ number: n, also_numbers: covers.filter((x) => x !== n) });
  const remove = (n) => set({ also_numbers: config.also_numbers.filter((x) => x !== n) });
  const add = () => {
    const n = Number(adding.replace(/^.*#/, "").trim());
    if (Number.isInteger(n) && n > 0 && !covers.includes(n)) set({ also_numbers: [...config.also_numbers, n] });
    setAdding("");
  };
  const refs = covers.map((n) => `${live.repo}#${n}`);
  const steward = live.by === STEWARD;
  const plannerName = NW_MODEL[live.planner_model || plannerModel] || plannerModel;
  const runPlanner = () => act.run(async () => {
    await post(`new-work/${live.id}/plan`, { number: config.number, also_numbers: config.also_numbers, notes: config.notes, planner_model: plannerModel });
    setEditing(false); setModel(null); setBrief(null);
  });
  const backToPlan = () => { set({ number: spec.number, also_numbers: spec.also_numbers || [], notes: spec.notes || "" }); setEditing(false); };
  const start = () => act.run(() => post(`new-work/${live.id}/approve`, { model: chosenModel, brief: shownBrief }));
  const stop = () => act.run(async () => { await post(`new-work/${live.id}/cancel`); onClose(); });
  const notNow = () => act.run(async () => { await post(`new-work/${live.id}/dismiss`); onClose(); });
  const done = state === "started" ? live.session : null;
  const running = state === "planning" || state === "starting";
  const status = form ? `The planner (${plannerName}) reads this first and writes a briefing. Nothing runs until you've read it.`
    : state === "planning" ? "You can close this: it keeps reading, and the plan shows up in Needs you."
    : review ? "Starting opens a real Claude session in tmux."
    : state === "starting" ? "Starting the session…"
    : state === "dismissed" ? "Set aside. Nothing ran."
    : "";
  return html`<dialog ref=${ref} class="nw sf" aria-labelledby="sf-h" onClose=${() => onClose()}>
    <div class="nw-head ${done ? "" : "agent"}">
      ${steward && !done && html`<span class="ask-avatar steward-mark" aria-hidden="true">S</span>`}
      <h2 id="sf-h">${done ? `${done} started` : `${steward ? "The Steward suggests" : `${live.by} suggests`} a session · ${live.title} ${refs[0] || ""}${refs.length > 1 ? `, also covering ${refs.slice(1).join(", ")}` : ""}`}</h2>
      <span style="flex: 1"></span>
      <button class="square" aria-label="Close" onClick=${() => onClose()}>×</button></div>
    ${done ? html`<div class="nw-body"><p>${refs.length > 1 ? `It covers ${refs.join(" and ")}. Each shows the session in Work, and its PR will close them all.` : `It works on ${refs[0]}, which shows the session in Work.`}</p></div>
      <div class="nw-foot"><a class="button primary" href=${hash("shells", { tab: "all", name: done })} onClick=${() => onClose()}>Open in Sessions</a><span style="flex: 1"></span><button class="plain" onClick=${() => onClose()}>Done</button></div>`
    : html`${live.why && html`<div class="nw-why"><span class="nw-why-word">why</span><span>${live.why}</span></div>`}
      <div class="nw-body">
        ${!config && !act.error && html`<p class="soft">Loading…</p>`}
        ${state === "failed" && html`<${Err} text=${live.error} />`}
        ${config && info && form && html`<div class="stack" style="gap: 6px"><span class="eyebrow">Covers</span>
          <div class="sf-covers">${covers.map((n, i) => html`<div class="sf-cover" key=${n}>
            <span class="nw-tag ${i === 0 ? "" : "quiet"}">${i === 0 ? "PRIMARY" : "ALSO COVERS"}</span>
            <span class="mono small">${live.repo}#${n}</span><span class="small" style="flex: 1 1 200px; min-width: 0">${titles[n] || "…"}</span>
            ${i > 0 && html`<button class="plain small-btn" onClick=${() => makePrimary(n)}>Make primary</button>
              <button class="square" aria-label=${`Remove ${live.repo}#${n}`} onClick=${() => remove(n)}>×</button>`}</div>`)}
            ${canAdd && html`<div class="row sf-add"><label class="row small" style="gap: 8px">Also cover ${live.repo}#<input class="mono" style="width: 90px" inputmode="numeric" aria-label=${`Another issue of ${live.repo} to cover`} value=${adding} onInput=${(e) => setAdding(e.target.value)} onKeyDown=${(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }} /></label>
              <button class="addlabel" disabled=${!adding.trim()} onClick=${add}>+ add</button></div>`}</div>
          <span class="small soft">${covers.length > 1 ? "Every issue here shows this session in Work, and the session is told to close all of them from its PR." : canAdd ? "Add issues the same change should close." : "A session on a pull request works on that one."}</span></div>
        <label class="nw-field">Notes — ${steward ? "the Steward" : live.by} proposed these; edit freely <span class="nw-sub">goes to the planner and the session</span>
          <textarea rows="3" value=${config.notes} onInput=${(e) => set({ notes: e.target.value })} /></label>
        <${PlannerModel} id="sf-pm" value=${plannerModel} onChange=${setPlannerModel} />`}
        ${state === "planning" && html`<div role="status" class="stack" style="gap: 8px">
          <span class="row" style="font-weight: 600; font-size: 18px"><${StateIcon} kind="run" />The planner is reading ${refs.join(", ")}</span>
          <span class="mono soft" style="font-size: 12.5px">claude -p · ${plannerName} · read-only hub tools · up to a few minutes</span>
          <p class="small soft">Nothing runs yet. You read the plan before any session starts.</p></div>`}
        ${review && info && spec && html`${live.error && html`<${Err} text=${`${live.error} The plan is still here: you can press Start again.`} />`}<div class="row" style="gap: 6px 12px; align-items: baseline"><h3>Review the plan</h3>
            <span class="small soft">written by the planner (${plannerName})${live.planner_cost_usd != null ? ` · $${live.planner_cost_usd.toFixed(2)}` : ""} · nothing has run yet</span></div>
          <dl class="defs"><dt>Covers</dt><dd>${refs.map((r, i) => html`<div key=${r}><span class="mono small">${r}</span> ${titles[covers[i]] || "…"}</div>`)}</dd>
            ${spec.notes && html`<dt>Notes</dt><dd>${spec.notes}</dd>`}
            <dt>Action</dt><dd>${live.title} · ${spec.persona}</dd>
            <dt>Effort</dt><dd>${spec.effort}</dd>
            ${preview && html`<dt>Branch</dt><dd>${preview.worktree}</dd><dt>Session</dt><dd class="mono" style="font-size: 13px">${preview.name}</dd>`}
            ${canAdd && html`<dt>PR body</dt><dd class="mono" style="white-space: pre-line; font-size: 13px">${covers.map((n) => `Closes #${n}`).join("\n")}</dd>`}</dl>
          <div class="stack" style="gap: 6px"><span id="sf-am" class="eyebrow">Agent model</span>
            <div role="radiogroup" aria-labelledby="sf-am" class="seg" style="align-self: flex-start">${info.models.map((m) => html`<button role="radio" aria-checked=${chosenModel === m ? "true" : "false"} onClick=${() => setModel(m)}>${NW_MODEL[m] || m}</button>`)}</div>
            <span class="small soft">${chosenModel === pick ? `${NW_MODEL[chosenModel] || chosenModel}: the planner’s pick for this work.` : `${NW_MODEL[chosenModel] || chosenModel}: your choice. The planner suggested ${NW_MODEL[pick] || pick}.`}</span></div>
          ${spec.docs.length > 0 && html`<div class="stack tight"><${Eyebrow}>Context · docs search${spec.docs_query ? ` “${spec.docs_query}”` : ""}<//>
            <ul class="stack" style="gap: 4px">${spec.docs.map((d) => html`<li class="passage"><span><b>${d.link}</b><span class="soft" style="font-size: 13px">${d.why}</span></span></li>`)}</ul></div>`}
          <label class="nw-field">Briefing <span class="nw-sub">the planner wrote this; edit freely · goes into the first prompt</span>
            <textarea class="mono" rows="6" value=${shownBrief} onInput=${(e) => setBrief(e.target.value)} /></label>
          ${preview && html`<details><summary class="eyebrow" style="min-height: 32px; cursor: pointer">The whole first prompt</summary><pre class="shadow" style="margin-top: 4px">${preview.prompt}</pre></details>`}`}
        <${Err} text=${act.error || previewError} />
      </div>
      <div class="nw-foot">
        ${form && html`<button class="primary" disabled=${act.busy || !config || Boolean(previewError)} onClick=${runPlanner}>Run the planner</button>`}
        ${planned && editing && html`<button class="plain" onClick=${backToPlan}>Back to the plan</button>`}
        ${state === "planning" && html`<button class="primary" disabled>Planning…</button>`}
        ${review && html`<button class="primary" disabled=${act.busy || !config || Boolean(previewError)} onClick=${start}>Start session</button>
          <button class="plain" disabled=${act.busy || !config} onClick=${runPlanner}>Re-plan</button>
          <button class="plain" onClick=${() => setEditing(true)}>Back to the form</button>`}
        ${state === "starting" && html`<button class="primary" disabled>Starting…</button>`}
        <span role="status" class="small" style="flex: 1 1 200px">${status}</span>
        ${running && html`<button class="plain" disabled=${act.busy} onClick=${stop}>${state === "planning" ? "Stop planner" : "Stop session"}</button>`}
        ${(state === "offered" || planned || state === "failed") && html`<button class="plain" disabled=${act.busy} onClick=${notNow}>Not now</button>`}
        <button class="plain" onClick=${() => onClose()}>${running ? "Close · keeps running" : "Close"}</button></div>`}</dialog>`;
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
        <button class="plain" onClick=${() => planWork({ id: item.id })}>Open in the planner</button>
        <${Discard} item=${item} reload=${reload} /></div></div></div>`;
}

function SuggestedSession({ item, compact, reload }) {
  const act = useAct(reload);
  const refs = [`${item.repo}#${item.number}`, ...(item.also_numbers || []).map((n) => `${item.repo}#${n}`)];
  return html`<article class="ask ${item.by === STEWARD ? "steward" : ""} ${compact ? "compact" : ""}">
    <div class="ask-head">${item.by === STEWARD && html`<span class="ask-avatar steward-mark" aria-hidden="true">S</span>`}<span class="small mono">${item.by}</span>${item.by === STEWARD && html`<span class="small">Steward</span>`}<span class="ask-kind">${item.state === "planned" ? (compact ? "SESSION · PLAN READY" : "PLAN READY") : item.state === "failed" ? "STOPPED" : compact ? "SESSION · SUGGESTED" : "SUGGESTED SESSION"}</span></div>
    <div class="ask-body"><h3 class="ask-title">${item.title} ${refs[0]}${refs.length > 1 ? `, also covering ${refs.slice(1).join(", ")}` : ""}</h3>
      <p class="small"><span class="nw-why-word" style="font-size: 17px">why </span>${item.why}</p>
      <p class="small soft">${item.notes ? `Proposed notes: “${item.notes}” ` : ""}${item.state === "planned" ? "The planner wrote a plan. Nothing has run: read it, and start the session if it's right." : "A planner reads this first. Nothing runs until you've read its plan."}</p>
      ${item.error && html`<p class="small" role="alert">${item.error}</p>`}<${Err} text=${act.error} />
      <div class="row"><button class="primary" onClick=${() => startForm(item)}>${item.state === "planned" ? "Read the plan" : "Open"}</button>
        <button class="plain" disabled=${act.busy} onClick=${() => act.run(() => post(`new-work/${item.id}/dismiss`))}>Not now</button></div></div></article>`;
}

function WorkWaiting({ item, compact, reload }) {
  if (item.number) return html`<${SuggestedSession} item=${item} compact=${compact} reload=${reload} />`;
  const act = useAct(reload);
  const steward = item.by === STEWARD;
  const undrafted = item.drafts.filter((d) => d.state === "draft").length;
  const line = item.state === "offered" ? item.why
    : item.state === "failed" ? item.error
    : item.state === "planned" && item.error ? item.error
    : item.state === "planned" ? "The planner wrote a spec. Nothing has run: read it, and start the session if it's right."
    : `${count(undrafted, "draft")} waiting for you.`;
  const kind = `${compact ? "NEW WORK · " : ""}${item.state === "offered" ? "SUGGESTED" : item.state === "failed" ? "STOPPED" : item.state === "planned" ? "PLAN READY" : "DRAFTS READY"}`;
  return html`<div class="ask ${steward ? "steward" : ""} ${compact ? "compact" : ""}">
    <div class="ask-head"><span class="ask-kind">${kind}</span><span class="small mono">${item.by === "you" ? "you" : item.by}</span><span class="small mono soft">${item.repo}</span></div>
    <div class="ask-body"><div class="ask-title">${item.title}</div><p class="small">${line}</p><${Err} text=${act.error} />
      <div class="row"><button class="primary" onClick=${() => planWork({ id: item.id })}>Open in the planner</button>
        <button class="plain" disabled=${act.busy} onClick=${() => act.run(() => post(`new-work/${item.id}/dismiss`))}>${item.state === "offered" ? "Not now" : "Set aside"}</button>
        ${item.state === "done" && html`<${Discard} item=${item} reload=${reload} />`}</div></div></div>`;
}

function Ask({ ask, compact, onDone, onShow }) {
  const steward = ask.session === STEWARD;
  const pending = ask.state === "pending";
  const permission = ask.kind === "permission";
  const questions = permission || !ask.input ? [] : ask.input.questions;
  const act = useAct(onDone);
  const [denying, setDenying] = useState(false);
  const [reason, setReason] = useState("");
  const [values, setValues] = useState({});
  const answer = (body) => act.run(() => post(`asks/${ask.id}/answer`, body));
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

// What each filter shows: its cards, whether suggested work belongs, and which decision requests do.
const ASK_FILTERS = [
  ["all", "All", () => true, () => true, () => true],
  ["perm", "Permissions", (a) => a.kind === "permission", () => false, () => false],
  ["ask", "Questions", (a) => a.kind === "question" && a.session !== STEWARD, () => false, () => false],
  ["suggest", "Suggestions", () => false, () => true, () => false],
  ["go", "Goes", () => false, () => false, (d) => d.kind === "go"],
  ["merge", "Merges", () => false, () => false, (d) => d.kind === "merge"],
  ["steward", "Steward", (a) => a.session === STEWARD, (i) => i.by === STEWARD, () => false],
];
const decisionsAsked = (asks) => asks.decisions.items.filter((d) => d.state === "requested");
const decisionsActive = (asks) => asks.decisions.items.filter((d) => d.state === "current" || d.state === "using");

function SessionTabs({ tab, asks }) {
  const active = decisionsActive(asks).length;
  return html`<div role="tablist" aria-label="Sessions" class="tabs" style="margin-bottom: 18px">
    <a role="tab" aria-selected=${tab === "needs" ? "true" : "false"} href=${hash("shells", { tab: "needs" })}>Needs you <span class="ask-tally ${asks.waiting ? "on" : ""}">${asks.waiting}</span></a>
    <a role="tab" aria-selected=${tab === "active" ? "true" : "false"} href=${hash("shells", { tab: "active" })}>Active${active > 0 ? ` (${active})` : ""}</a>
    <a role="tab" aria-selected=${tab === "all" ? "true" : "false"} href=${hash("shells", { tab: "all" })}>All sessions</a>
    <a role="tab" aria-selected=${tab === "history" ? "true" : "false"} href=${hash("shells", { tab: "history" })}>History & cleanup</a></div>`;
}

function Inbox({ asks }) {
  const [filter, setFilter] = useState("all");
  const [chosen, setChosen] = useState(null);
  const open = asks.open;
  const aside = asks.work.items.filter((i) => i.state === "dismissed" && i.drafts.length > 0);
  const [, , test, showsWork, showsDecision] = ASK_FILTERS.find(([id]) => id === filter);
  const planned = asks.work.items.filter(nwWaits).filter(showsWork);
  const decisions = decisionsAsked(asks).filter(showsDecision);
  const shown = open.filter(test);
  const fromSteward = shown.filter((a) => a.session === STEWARD);
  const fromSessions = shown.filter((a) => a.session !== STEWARD);
  const done = asks.answered.filter(test);
  // The one you pointed at, while it has something open; else the oldest.
  const live = open.some((a) => a.session === chosen) ? chosen : open.length ? open[0].session : null;
  const card = (a) => html`<${Ask} key=${a.id} ask=${a} onDone=${asks.reload} onShow=${setChosen} />`;
  return html`<main class="page wide"><${SessionTabs} tab="needs" asks=${asks} />
    <div class="inbox">
      <section class="stack" style="gap: 18px; flex: 999 1 560px; min-width: 0" aria-label="Needs you">
        <div role="group" aria-label="Show" class="row" style="gap: 6px">${ASK_FILTERS.map(([id, label]) => html`<button class="ask-filter" aria-pressed=${filter === id ? "true" : "false"} onClick=${() => setFilter(id)}>${label}</button>`)}</div>
        ${(filter === "all" || filter === "go") && html`<${GoPanel} asks=${asks} />`}
        ${planned.length > 0 && html`<div class="stack" style="gap: 10px"><h2 class="eyebrow">Suggested sessions and new work</h2>${planned.map((item) => html`<${WorkWaiting} key=${item.id} item=${item} reload=${asks.reload} />`)}</div>`}
        ${asks.waiting === 0 && html`<div role="status" class="ask-clear"><span class="ask-clear-word">all clear</span><span>Nothing is waiting on you. Sessions keep working, and anything new shows up here and on the Sessions badge.</span></div>`}
        ${decisions.length > 0 && html`<div class="stack" style="gap: 10px"><div class="row" style="gap: 10px"><h2 class="eyebrow">Decisions asked for</h2><span class="small soft">Nothing happens until you approve. Only a login records one, and what a session says in its own words isn't yours.</span></div>${decisions.map((d) => html`<${DecisionRow} key=${`${d.id}-${d.state}`} d=${d} onChanged=${asks.decisions.reload} />`)}</div>`}
        ${fromSteward.length > 0 && html`<div class="stack" style="gap: 10px"><div class="row" style="gap: 10px"><h2 class="eyebrow">From the Steward</h2><span class="small soft">The same question is pinned in the Steward sidebar. Answer either one.</span></div>${fromSteward.map(card)}</div>`}
        ${fromSessions.length > 0 && html`<div class="stack" style="gap: 10px"><h2 class="eyebrow">From sessions · oldest first</h2>${fromSessions.map(card)}</div>`}
        ${aside.length > 0 && html`<details class="ask-answered"><summary class="eyebrow">Set aside · ${aside.length}</summary>
          <div class="stack" style="gap: 10px; margin-top: 10px">${aside.map((item) => html`<${SetAside} key=${item.id} item=${item} reload=${asks.reload} />`)}</div>
          <p class="small soft" style="margin-top: 8px">The oldest finished work goes once more than 50 are kept.</p></details>`}
        ${filter !== "all" && asks.waiting > 0 && !shown.length && !planned.length && !decisions.length && html`<p class="small soft">Nothing of this kind is waiting. ${asks.waiting} ${asks.waiting === 1 ? "thing is" : "things are"} waiting under All.</p>`}
        ${done.length > 0 && html`<details class="ask-answered"><summary class="eyebrow">Answered today · ${done.length}</summary>
          <div class="stack" style="gap: 10px; margin-top: 10px">${done.map((a) => html`<${Ask} key=${a.id} ask=${a} compact />`)}</div>
          <p class="small soft" style="margin-top: 8px">Kept until hubd restarts.</p></details>`}
      </section>
      ${live && html`<aside class="termbox inbox-term" aria-labelledby="h-live">
        <div class="termhead"><h2 id="h-live">${live}</h2><span class="small soft" style="flex: 1 1 160px">live terminal · the same prompt</span>
          <a class="button" href=${hash("shells", { tab: "all", name: live })}>Attach</a></div>
        <${TerminalView} key=${live} name=${live} quiet onGone=${asks.reload} />
        <p class="small soft" style="padding: 10px 16px; border-top: 1.5px solid var(--ink)">A hook asks hub and waits. The terminal keeps its own prompt. Whichever answer comes first wins, and the other side closes.</p></aside>`}
    </div></main>`;
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
  const { data, error, reload } = useLoad(() => post("agents/past"), []);
  const [filter, setFilter] = useState("all");
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
  const rows = (data ? data.sessions : []).filter((r) => (filter === "all" || r.kind === filter) && (!found || found.matches[r.id]));
  const resume = (r) => act.run(async () => { await post("agents/resume_past", { id: r.id }); setBack(r.name); });
  return html`<section class="stack" style="gap: 14px" aria-labelledby="h-hist">
    ${reading && html`<${Transcript} id=${reading.id} name=${reading.name} onClose=${() => setReading(null)} />`}
    <div class="row" style="justify-content: space-between; align-items: flex-end; gap: 12px 20px">
      <div class="stack tight" style="flex: 1 1 380px"><h1 id="h-hist">Resume a past session</h1>
        <span class="small soft">Every session that has ended, with its transcript. Resuming reopens it in tmux with <span class="mono">claude --resume</span>, right where it stopped.</span></div>
      <input type="search" aria-label="Search transcripts" placeholder="Search transcripts" style="flex: 0 1 320px" value=${words} onInput=${(e) => setWords(e.target.value)} /></div>
    <div role="group" aria-label="Filter" class="row" style="gap: 6px">${PAST_FILTERS.map(([id, label]) => html`<button class="ask-filter" aria-pressed=${filter === id ? "true" : "false"} onClick=${() => setFilter(id)}>${label}</button>`)}
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
        ${r.transcript ? html`<button class="primary" disabled=${act.busy} onClick=${() => resume(r)}>${r.worktree === "removed" ? "Restore & resume" : "Resume"}</button>
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
      <button disabled=${!safe.length} onClick=${() => setPicked(Object.fromEntries(safe.map((r) => [r.id, true])))}>Select everything safe</button>
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
      <div class="stack" style="gap: 2px; flex: 999 1 280px; min-width: 0"><span class="mono small clean-path">${r.path}</span><span class="small soft">${r.what}</span></div>
      <span class="past-tag ${r.state}">${CLEAN_TAG[r.state]}</span><span class="mono small" style="flex: none; min-width: 64px; text-align: right">${bytes(r.size)}</span></div>`)}</div>
    ${data && html`<div class="stack" style="gap: 6px; padding-top: 12px; border-top: 1px dotted var(--ink)"><span class="eyebrow">Clean up by itself</span>
      <label class="row small" style="gap: 8px"><input type="checkbox" checked=${data.settings.after_merge} disabled=${act.busy} onChange=${(e) => setAfterMerge(e.target.checked)} /> Remove a session's worktree ${data.settings.days} days after its pull request merges</label>
      <span class="small soft">Only rows that are safe to remove. Anything with uncommitted files, unpushed commits or a running session is never removed by itself, and neither is anything the hub didn't start. Transcripts are never deleted.</span></div>`}
  </section>`;
}

function SessionHistory({ asks }) {
  return html`<main class="page wide"><${SessionTabs} tab="history" asks=${asks} /><div class="stack" style="gap: 32px"><${PastSessions} /><${Cleanup} /></div></main>`;
}

// What you've allowed that still stands, so a go can be ended early. Ended ones stay on the Decisions page.
function ActiveDecisions({ asks }) {
  const active = decisionsActive(asks);
  return html`<main class="page wide"><${SessionTabs} tab="active" asks=${asks} />
    <section class="stack" style="gap: 14px; max-width: 760px" aria-labelledby="h-active">
      <div class="stack tight"><h1 id="h-active">Active</h1>
        <span class="small soft">Goes and merge decisions you've approved that still stand. A go ends when its runs or hours are used up; end it here to stop it sooner. A session can end a go too, and nothing it says makes one current.</span></div>
      ${asks.decisions.error && html`<${Err} text=${asks.decisions.error} />`}
      ${active.map((d) => html`<${DecisionRow} key=${`${d.id}-${d.state}`} d=${d} onChanged=${asks.decisions.reload} />`)}
      ${!active.length && html`<p class="small soft">Nothing you've allowed is standing.</p>`}
      <p class="small"><a href=${hash("decisions")}>All decisions, including ended ones →</a> <a href=${hash("shells", { tab: "needs" })}>Record a go, under Needs you →</a></p>
    </section></main>`;
}

function Sessions({ query, asks }) {
  const tab = query.tab || (query.name || query.new ? "all" : "needs");
  if (tab === "needs") return html`<${Inbox} asks=${asks} />`;
  if (tab === "active") return html`<${ActiveDecisions} asks=${asks} />`;
  if (tab === "history") return html`<${SessionHistory} asks=${asks} />`;
  return html`<${Shells} query=${query} asks=${asks} />`;
}

function Shells({ query, asks }) {
  const [kept, setKept] = useState(null);
  const { data, error, reload } = useLoad(() => api("shells"), [], 15000);
  const stopped = useLoad(() => api("agents/stopped").catch(() => []), [], 15000);
  const reloadAll = () => Promise.all([reload(), stopped.reload()]);
  const [discarding, setDiscarding] = useState(null);
  const [ignoring, setIgnoring] = useState(null);
  const [open, setOpen] = useState(query.name || null);
  const [creating, setCreating] = useState(query.new === "1");
  const [confirm, dialog] = useConfirm();
  const act = useAct(reloadAll);
  const focus = useRef(null);
  const list = data || [];
  const current = list.find((s) => s.name === open) || null;
  // Closed first: the old terminal goes away with the old session, and would close the new one's view.
  const resume = (name) => act.run(async () => {
    setOpen(null);
    await post("agents/resume", { name });
    await reloadAll();
    setOpen(name);
  });
  const item = (s) => {
    const a = s.agent;
    const state = a ? (a.ended ? "ended" : a.waiting ? "waiting" : "running") : s.attached > 0 ? "attached" : "idle";
    return html`<button class="sess-item" aria-pressed=${open === s.name ? "true" : "false"} onClick=${() => setOpen(s.name)}>
      <span class="h"><b>${s.name}</b><span class="badge ${state === "waiting" ? "mark" : state === "attached" ? "dim" : ""}">${state}</span></span>
      ${a && html`<span class="row" style="gap: 4px 8px; font-size: 13px"><b style="font-weight: 600">${a.persona}</b><span class="mono soft" style="font-size: 12px">${shortModel(a.model)}</span></span>`}
      <span class="soft" style="font-size: 13px; line-height: 1.4">${a ? `${a.title} · ${whereFrom(a)}` : s.cwd}</span></button>`;
  };
  const managed = list.filter((s) => s.agent && !s.agent.started_by);
  const started = list.filter((s) => s.agent && s.agent.started_by);
  const startedWorking = started.filter((s) => !s.agent.ended && !s.agent.idle).length;
  const plain = list.filter((s) => !s.agent);
  const currentAsks = current ? asks.open.filter((a) => a.session === current.name) : [];
  return html`${dialog}<main class="page wide"><${SessionTabs} tab="all" asks=${asks} /><div class="columns near">
    <nav class="sesslist" aria-labelledby="h-sessions">
      <h1 id="h-sessions">Sessions</h1>
      <span class="mono soft dotted" style="font-size: 12.5px">tmux -L glassine-hub</span>
      <button onClick=${() => setCreating(true)}>Plain shell</button>
      ${creating && html`<${NewShell} initial=${query.name && query.new ? query.name : ""} onCancel=${() => setCreating(false)} onDone=${async (n) => { setCreating(false); await reload(); setOpen(n); }} />`}
      <${Err} text=${error || act.error} />
      ${kept && html`<div class="notice quiet"><span>That session had work that isn't on GitHub, so its checkout stays at <code>${kept}</code>.</span></div>`}
      <h2 class="eyebrow" style="margin-top: 8px">Managed Claude sessions</h2>
      ${managed.map(item)}
      ${!managed.length && !started.length && html`<p class="small soft">Start one from an issue, pull request or run under Work.</p>`}
      ${started.length > 0 && html`<h2 class="eyebrow" style="margin-top: 8px">Started by the Steward · ${startedWorking} of 4 working</h2>${started.map(item)}`}
      ${(stopped.data || []).length > 0 && html`<h2 class="eyebrow" style="margin-top: 8px">Stopped</h2>
        ${stopped.data.map((s) => html`<div class="stack" style="gap: 4px; padding: 8px 0; border-top: 1px dotted var(--ink)">
          <span class="row" style="justify-content: space-between"><b class="mono" style="font-size: 13.5px; overflow-wrap: anywhere">${s.name}</b><span class="badge dim">stopped</span></span>
          <span class="soft" style="font-size: 13px">${s.agent.title} · ${whereFrom(s.agent)}${s.agent.started_by ? ` · started by ${s.agent.started_by}` : ""}</span>
          <span class="row" style="gap: 8px"><button disabled=${act.busy} onClick=${() => resume(s.name)}>Resume</button>
            <button class="plain" disabled=${act.busy} onClick=${() => setDiscarding(s.name)}>Discard…</button></span></div>`)}`}
      <h2 class="eyebrow" style="margin-top: 8px">Plain shells</h2>
      ${plain.map(item)}
      ${!plain.length && html`<p class="small soft">None open.</p>`}
    </nav>
    <section class="termbox" aria-labelledby="h-term">
      ${current ? html`<div class="termhead"><h2 id="h-term">${current.name}</h2>
          <span class="mono soft" style="font-size: 13px; flex: 1 1 200px; overflow-wrap: anywhere">${current.cwd}</span>
          <button class="plain" onClick=${() => setOpen(null)}>Detach</button>
          <button class="plain" disabled=${act.busy} onClick=${() => confirm(
            { title: "End this session?", text: `Ends “${current.name}” and everything running in it.`, label: "End session", danger: true },
            () => act.run(async () => {
              const r = await api(`shells/${encodeURIComponent(current.name)}`, { method: "DELETE" });
              setKept(r && r.kept ? r.kept : null);
              setOpen(null);
            }),
          )}>End…</button></div>
        ${currentAsks.length > 0 && html`<div class="session-asks stack" style="gap: 10px">${currentAsks.map((a) => html`<${Ask} key=${a.id} ask=${a} onDone=${asks.reload} />`)}</div>`}
        ${current.agent && current.agent.waiting && !currentAsks.length && html`<div role="status" class="waitbar"><span>Waiting for you: answer in the terminal below.</span>
          <button class="plain" onClick=${() => focus.current && focus.current()}>Jump to prompt</button></div>`}
        ${current.agent && current.agent.ended && html`<div role="status" class="waitbar"><span>Claude has ended in this session.</span>
          <button class="plain" disabled=${act.busy} onClick=${() => confirm(
            { title: "Resume this session?", text: "Its conversation continues in a new terminal. The shell open here closes, with anything running in it.", label: "Resume" },
            () => resume(current.name),
          )}>Resume…</button></div>`}
        <${TerminalView} key=${current.name} name=${current.name} focusRef=${focus} onGone=${() => { setOpen(null); reload(); }} />`
      : html`<div class="empty" id="h-term">${list.length || (stopped.data || []).length ? "Choose a session." : "No sessions yet."}</div>`}
    </section>
    <${Manifest} key=${current ? current.name : "none"} session=${current} work=${asks.work} />
    ${discarding && html`<${Confirm} title=${`Discard ${discarding}?`} danger label="Discard"
      text="It can't be resumed after this. Its worktree goes, with anything uncommitted in it. Commits stay on the branch."
      onNo=${() => setDiscarding(null)} onYes=${() => { const name = discarding; setDiscarding(null);
        act.run(async () => { const r = await api(`shells/${encodeURIComponent(name)}?discard=1`, { method: "DELETE" }); if (r && r.ignored) setIgnoring({ name, ignored: r.ignored }); }); }} />`}
    ${ignoring && html`<${DiscardIgnored} item=${ignoring} onNo=${() => setIgnoring(null)} onYes=${() => { const name = ignoring.name; setIgnoring(null);
        act.run(() => api(`shells/${encodeURIComponent(name)}?discard=1&drop_ignored=1`, { method: "DELETE" })); }} />`}
  </div></main>`;
}

// --- advanced mode ---------------------------------------------------------------------------------
function Launch({ query }) {
  const { repo } = query;
  const number = Number(query.number);
  const handoff = useRef(advancedHandoff);
  advancedHandoff = null;
  const [actionId, setActionId] = useState(query.action);
  const [config, setConfig] = useState(handoff.current);
  const [info, setInfo] = useState(null);
  const [siblings, setSiblings] = useState([]);
  const [preview, setPreview] = useState(null);
  const [previewError, setPreviewError] = useState(null);
  const [docsQuery, setDocsQuery] = useState(handoff.current ? handoff.current.docs_query || "" : "");
  const [found, setFound] = useState([]);
  const overview = useLoad(() => api("overview"), []);
  const repoNames = overview.data ? overview.data.groups.flatMap((g) => g.repos.map((r) => r.name)) : [];
  const act = useAct();
  const search = useAct();
  const set = (patch) => setConfig((c) => ({ ...c, ...patch }));
  const [plannerModel, setPlannerModel] = useState(PLANNER_DEFAULT);
  const carried = useRef(null); // your notes and pins, when you switch action
  const steerKey = info && `${info.object}/${repo}/${number}`;
  useEffect(() => {
    if (!config || !steerKey) return;
    if ((config.notes || "").trim() || (config.pins || []).length) steering.set(steerKey, { notes: config.notes || "", pins: config.pins || [] });
    else steering.delete(steerKey);
  }, [config && config.notes, config && config.pins, steerKey]);
  useEffect(() => {
    act.run(async () => {
      const a = (await post("agents/action", { action: actionId })).action;
      setInfo(a);
      setSiblings(await api(`agents/actions${params({ object: a.object })}`));
      if (!config || config.action !== actionId) {
        const fresh = (await post("agents/defaults", { action: actionId, repo, number })).config;
        const yours = carried.current || steering.get(`${a.object}/${repo}/${number}`) || {};
        setConfig({ ...fresh, notes: yours.notes || "", pins: yours.pins || [], also_numbers: [] });
      }
    });
  }, [actionId]);
  useEffect(() => {
    if (!config) return undefined;
    const timer = setTimeout(async () => {
      try { setPreview(await post("agents/preview", { config })); setPreviewError(null); } catch (e) { setPreviewError(e.message); }
    }, 250);
    return () => clearTimeout(timer);
  }, [config]);
  const replan = () => act.run(async () => { const r = await post("agents/plan", { action: actionId, repo, number, notes: config.notes, pins: config.pins, planner_model: plannerModel }); setConfig({ ...r.config, also_numbers: config.also_numbers || [] }); setDocsQuery(r.config.docs_query || ""); });
  const start = () => act.run(async () => { const r = await post("agents/start", { config }); if (steerKey) steering.delete(steerKey); location.hash = hash("shells", { name: r.name }); });
  const toggleDoc = (link, why) => set({ docs: config.docs.some((d) => d.link === link) ? config.docs.filter((d) => d.link !== link) : [...config.docs, { link, why: why.slice(0, 300) }] });
  const toggle = (field, name) => set({ [field]: config[field].includes(name) ? config[field].filter((t) => t !== name) : [...config[field], name] });
  const tab = { pr: "prs", issue: "issues", run: "actions" }[info ? info.object : "issue"];
  if (!repo || !number) return html`<main class="page"><${Err} text="Open advanced mode from an issue, pull request or run." /></main>`;
  const passages = config ? [...config.docs.map((d) => ({ link: d.link, why: d.why })), ...found.filter((f) => !config.docs.some((d) => d.link === f.link))] : [];
  return html`<main class="page wide" style="gap: 24px">
    <div class="stack tight"><a class="small" style="align-self: flex-start; font-weight: 500" href=${hash("work", { tab, repo, item: number })}>← Back to the item</a>
      <${Eyebrow} soft>Advanced mode<//><h1>Session spec</h1></div>
    <div class="notice" style="flex-wrap: wrap"><span style="flex: 1 1 100%">${handoff.current ? "The planner filled this in" : "Starts from the action's defaults"} for <span class="mono">${repo}#${number}</span>. Change anything; hub still refuses what this action doesn't allow.</span>
      ${config && info && html`<div class="grow"><${SteerFields} kind=${info.object} notes=${config.notes || ""} pins=${config.pins || []} onNotes=${(notes) => set({ notes })} onPins=${(pins) => set({ pins })} /></div>`}
      <label class="field" style="align-self: flex-end"><span>Planner</span><select value=${plannerModel} onChange=${(e) => setPlannerModel(e.target.value)}>${PLANNER_CHOICES.map((m) => html`<option value=${m}>${NW_MODEL[m]}</option>`)}</select></label>
      <button class="plain" style="align-self: flex-end" disabled=${act.busy || !config} onClick=${replan}>${act.busy ? "Working…" : handoff.current ? "Re-plan with notes" : "Plan it"}</button></div>
    <${Err} text=${act.error} />
    ${config && info && html`<div class="columns">
      <div class="wide stack" style="gap: 32px">
        <section class="step" aria-labelledby="h-p"><div class="step-head"><i aria-hidden="true">1</i><h2 id="h-p">Persona</h2></div>
          <div role="radiogroup" aria-labelledby="h-p" class="choices">${info.personas.map((p) => html`<button role="radio" class="choice" aria-checked=${config.persona === p.id ? "true" : "false"} onClick=${() => set({ persona: p.id })}>
            <b>${p.id}</b><span class="soft" style="font-size: 13.5px; line-height: 1.4">${p.text.slice(0, 140)}${p.text.length > 140 ? "…" : ""}</span></button>`)}</div>
          <div class="row"><label class="field"><span>Model</span><select value=${config.model} onChange=${(e) => set({ model: e.target.value })}>${info.models.map((m) => html`<option value=${m}>${m}</option>`)}</select></label>
            <label class="field"><span>Effort</span><select value=${config.effort} onChange=${(e) => set({ effort: e.target.value })}>${info.efforts.map((m) => html`<option value=${m}>${m}</option>`)}</select></label></div>
        </section>
        <section class="step" aria-labelledby="h-t"><div class="step-head"><i aria-hidden="true">2</i><h2 id="h-t">Prompt builder</h2></div>
          <div role="tablist" aria-label="Prompt builder" class="row" style="gap: 6px">${siblings.map((a) => html`<button role="tab" class="pill" aria-selected=${a.id === actionId ? "true" : "false"} onClick=${() => { if (config) carried.current = { notes: config.notes, pins: config.pins }; setConfig(null); setActionId(a.id); }}>${a.title}</button>`)}</div>
          <p class="small soft">${info.summary}</p>
          ${info.full && info.object === "issue" && html`<label class="field"><span>Also covers issues of ${repo}</span>
            <input class="mono" placeholder="e.g. 11, 14" value=${(config.also_numbers || []).join(", ")} onChange=${(e) => set({ also_numbers: [...new Set((e.target.value.match(/\d+/g) || []).map(Number))] })} /></label>`}
          ${info.full && info.checkout && html`<div class="stack tight"><span class="eyebrow">Also check out</span>
            <div class="row" style="gap: 6px">${repoNames.filter((n) => n !== repo).map((n) => {
              const on = (config.also_repos || []).includes(n);
              return html`<button class="pill" aria-pressed=${on ? "true" : "false"} onClick=${() => set({ also_repos: on ? config.also_repos.filter((r) => r !== n) : [...(config.also_repos || []), n] })}>${n}</button>`;
            })}</div></div>`}
          <label class="field"><span>Briefing, added to the action's prompt</span>
            <textarea rows="8" value=${config.brief} onInput=${(e) => set({ brief: e.target.value })}></textarea></label>
        </section>
        <section class="step" aria-labelledby="h-c"><div class="step-head"><i aria-hidden="true">3</i><h2 id="h-c">Context from docs search</h2>
            <span class="mono soft" style="font-size: 12.5px">${config.docs.length} included</span></div>
          <form class="searchbox" role="search" style="flex: none" onSubmit=${(e) => { e.preventDefault(); search.run(async () => {
            const r = await api(`docs/search${params({ q: docsQuery })}`);
            setFound(r.results.map((h) => ({ link: h.url, why: h.heading || h.title, snippet: h.text.slice(0, 160) })));
            set({ docs_query: docsQuery });
          }); }}><${SearchIcon} /><label class="sr" for="adv-q">Search query</label>
            <input id="adv-q" type="search" placeholder="Search, then tick what the agent should read" value=${docsQuery} onInput=${(e) => setDocsQuery(e.target.value)} /></form>
          <${Err} text=${search.error} />
          ${passages.map((p) => {
            const on = config.docs.some((d) => d.link === p.link);
            return html`<button class="pick" aria-pressed=${on ? "true" : "false"} onClick=${() => toggleDoc(p.link, p.why)}>
              <span class="box" aria-hidden="true">${on && html`<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 7.2l2.6 2.6L11 4.4" /></svg>`}</span>
              <span><b class="mono" style="font-size: 13px; overflow-wrap: anywhere">${urlPath(p.link)}</b><span class="soft" style="font-size: 14px; line-height: 1.45">${p.snippet || p.why}</span></span></button>`;
          })}
        </section>
        <section class="step" aria-labelledby="h-k"><div class="step-head"><i aria-hidden="true">4</i><h2 id="h-k">Skills and hub tools</h2></div>
          <div class="row" style="gap: 8px">${info.skills.map((s) => html`<span class="badge" style="text-transform: none; letter-spacing: 0; font-size: 12.5px">${s}</span>`)}</div>
          ${info.full ? html`<p>Full Claude Code, with your rights: it has every tool, and your project's settings apply.</p>`
            : html`<div class="tools">${[["tools", info.tools], ["hub_tools", info.hub_tools]].flatMap(([field, names]) => names.map((name) => {
                const on = config[field].includes(name);
                return html`<div><span>${name}</span><div role="radiogroup" aria-label=${name} class="seg">
                  <button role="radio" aria-checked=${on ? "false" : "true"} onClick=${() => on && toggle(field, name)}>Off</button>
                  <button role="radio" aria-checked=${on ? "true" : "false"} onClick=${() => !on && toggle(field, name)}>Allow</button></div></div>`;
              }))}</div>`}
          <p class="small soft">${info.ceiling}</p>
        </section>
      </div>
      <aside class="aside panel" aria-labelledby="h-prev" style="flex-basis: 400px; gap: 14px">
        <h2 id="h-prev" class="eyebrow">What hub will start</h2>
        <label class="field"><span>Session name</span><input class="mono" value=${config.name || (preview ? preview.name : "")} onInput=${(e) => set({ name: e.target.value || undefined })} /></label>
        <${Err} text=${previewError} />
        ${preview && html`<div class="stack" style="gap: 4px"><${Eyebrow}>Command<//><pre class="dark">$ ${preview.command}</pre></div>
          <div class="stack" style="gap: 4px"><${Eyebrow}>First prompt<//><pre class="shadow">${preview.prompt}</pre></div>
          <dl class="defs"><dt>Worktree</dt><dd>${preview.worktree}</dd>
            ${preview.checkouts.map((c) => html`<dt>In</dt><dd class="mono" style="font-size: 13px; overflow-wrap: anywhere">${c}</dd>`)}
            <dt>Runs from</dt><dd class="mono" style="font-size: 13px; overflow-wrap: anywhere">${preview.cwd}</dd></dl>`}
        <details><summary class="eyebrow" style="min-height: 32px; cursor: pointer">Spec JSON</summary><pre class="shadow" style="margin-top: 4px">${JSON.stringify(config, null, 2)}</pre></details>
        <div class="row"><button class="primary" disabled=${act.busy || Boolean(previewError)} onClick=${start}>Start session</button></div>
      </aside></div>`}
  </main>`;
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

function Budget() {
  const { data } = useLoad(() => api("limits"), [], 120000);
  if (!data) return null;
  const pct = data.limit ? Math.round(data.remaining / data.limit * 100) : 0;
  const reset = new Date(data.reset * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return html`<span class="budget" title="GitHub API budget"><b>API</b>
    <span class="bar ink" style="width: 64px; height: 8px"><i style="width: ${pct}%"></i></span>
    ${data.remaining.toLocaleString()} / ${data.limit.toLocaleString()} · resets ${reset}</span>`;
}

// --- the device view ------------------------------------------------------------------------------
function DeviceView() {
  const { data, error } = useLoad(() => api("device"), [], 15000);
  return html`<main class="page close" aria-labelledby="h-device">
    <div class="stack tight"><h1 id="h-device">Device</h1>
      <span class="small soft">What each device last reported, in words with an age. The hub never asks the device, runs no tests and doesn't take the lock.</span></div>
    ${error && html`<div class="error" role="alert">No view: the hub can't read it (${error}). Nothing is lost: <span class="mono">dev status</span> asks the device, and its files are there.</div>`}
    ${data && data.devices.map((d) => html`<article class="stack" style="gap: 6px" key=${d.device || "none"}>
      ${d.device && html`<h3 class="mono" style="font-size: 15px">${d.device}</h3>`}
      ${d.lines.map((line) => html`<p style="overflow-wrap: anywhere">${line}.</p>`)}</article>`)}
    ${data && html`<p class="small soft">${data.only}</p>`}
    <p class="small">Recording a go, and “I've got the device”, are under <a href=${hash("shells", { tab: "needs" })}>Sessions › Needs you</a>. What stands is under <a href=${hash("shells", { tab: "active" })}>Active</a>.</p>
  </main>`;
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
      ${!form && html`<button class="primary" onClick=${() => setForm(true)}>Go…</button>`}
      ${holding && (holding.holding
        ? html`<button disabled=${act.busy} onClick=${() => hold(false)}>Done</button>`
        : html`<button disabled=${act.busy} onClick=${() => hold(true)}>I've got the device</button>`)}
      <span class="small soft">Ends every device go but an eye test, and refuses a take that names actions until you press Done. It can't stop a running command.</span></div>
    ${form && html`<${GoForm} devices=${(device.data ? device.data.devices : []).map((d) => d.device).filter(Boolean)} onDone=${() => { setForm(false); return asks.decisions.reload(); }} onCancel=${() => setForm(false)} />`}
  </section>`;
}

// --- the Decisions page ---------------------------------------------------------------------------
const DECISION_STATE = { requested: "Waiting for you", current: "Current", using: "Merging now", ended: "Ended" };
const DECISION_BADGE = { requested: "mark", current: "", using: "mark", ended: "dim" };

function DecisionRow({ d, onChanged }) {
  const act = useAct(onChanged);
  const [words, setWords] = useState("");
  const [narrow, setNarrow] = useState(null);
  const [reason, setReason] = useState("");
  const go = d.kind === "go";
  const asked = d.state === "requested";
  const actions = narrow || (go ? d.scope.actions : []);
  const toggle = (a) => setNarrow(actions.includes(a) ? actions.filter((x) => x !== a) : [...actions, a]);
  const approve = () => act.run(() => post(`decisions/${d.id}/approve`, { words: words || null, scope: narrow ? { actions: narrow } : null }));
  return html`<article class="stack" style="gap: 6px; padding: 10px 0; border-bottom: 1px solid var(--rule)" aria-label=${`${DECISION_STATE[d.state]}: ${d.says}`}>
    <div class="row" style="gap: 8px"><span class="badge ${DECISION_BADGE[d.state]}">${DECISION_STATE[d.state]}</span><span class="mono small">${d.id}</span>
      <span class="small soft">made ${ago(d.made * 1000)}${d.ended ? `, ended ${ago(d.ended * 1000)}` : ""}</span></div>
    <p style="overflow-wrap: anywhere">${d.says}.</p>
    ${d.words && html`<p class="small" style="overflow-wrap: anywhere"><span class="soft">Your words: </span>${d.words}</p>`}
    ${d.asked_by && html`<p class="small soft">Asked for by ${d.asked_by}, in its own words, which aren't yours: <span style="overflow-wrap: anywhere">${d.why}</span></p>`}
    ${!d.asked_by && d.why && html`<p class="small soft" style="overflow-wrap: anywhere">Asked for by a hub shell, in its own words: ${d.why}</p>`}
    ${d.why_ended && html`<p class="small">Ended: ${d.why_ended}</p>`}
    ${asked && html`<div class="stack" style="gap: 8px">
      ${go && html`<fieldset class="row" style="gap: 6px 14px; border: 0; padding: 0"><legend class="small soft">Untick what you don't want to allow</legend>
        ${d.scope.actions.map((a) => html`<label class="row small" style="gap: 6px"><input type="checkbox" checked=${actions.includes(a)} onChange=${() => toggle(a)} /> ${a}</label>`)}</fieldset>`}
      <label class="stack small" style="gap: 4px">Your words, if you want them on the record<input value=${words} onInput=${(e) => setWords(e.target.value)} /></label>
      <div class="row" style="gap: 8px"><button class="primary" disabled=${act.busy || (go && !actions.length)} onClick=${approve}>Approve</button>
        <input aria-label="Why not" value=${reason} placeholder="Why not, if you like" onInput=${(e) => setReason(e.target.value)} />
        <button disabled=${act.busy} onClick=${() => act.run(() => post(`decisions/${d.id}/deny`, { why: reason || null }))}>Say no</button></div></div>`}
    ${d.state === "current" && html`<div class="row"><button disabled=${act.busy} onClick=${() => act.run(() => post(`decisions/${d.id}/end`, {}))}>End this</button></div>`}
    <${Err} text=${act.error} /></article>`;
}

function DecisionsPage() {
  const { data, error, reload } = useLoad(() => api("decisions"), [], 5000);
  const rows = data ? data.decisions : [];
  const part = (state, title, none) => { const here = rows.filter((d) => d.state === state);
    return html`<section class="stack" style="gap: 4px"><h3 style="font-size: 15px">${title} (${here.length})</h3>
      ${here.map((d) => html`<${DecisionRow} key=${`${d.id}-${d.state}`} d=${d} onChanged=${reload} />`)}
      ${!here.length && html`<p class="small soft">${none}</p>`}</section>`; };
  return html`<main class="page close" aria-labelledby="h-decisions">
    <div class="stack tight"><h1 id="h-decisions">Decisions</h1>
      <span class="small soft">Your word, kept. Only a login records one: a session can ask for one and can end a go, and nothing it says makes one current. Approved here means your decision, never a GitHub review.</span></div>
    <${Err} text=${error} />
    ${data && html`<p role="status" class="small">${data.holding.words} <a href=${hash("device")}>Device →</a></p>`}
    <div class="row" style="gap: 8px"><a class="button" href=${hash("device")}>Go, on the Device page</a></div>
    ${part("requested", "Waiting for you", "Nothing is waiting for you.")}
    ${rows.some((d) => d.state === "using") && part("using", "Merging now", "")}
    ${part("current", "Current", "No decision is current.")}
    ${part("ended", "Ended", "Nothing has ended yet.")}
  </main>`;
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
    <${DocsTabs} tab="notes" />
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

const NAV = [["overview", "Overview"], ["roadmap", "Roadmap"], ["work", "Work"], ["docs", "Docs"], ["shells", "Sessions"], ["device", "Device"]];

// --- the Steward ---------------------------------------------------------------------------------
const STEWARD = "steward";
const SEEN_KIND = { issues: "issue", prs: "pull request", actions: "run" };
const SEEN_SCREEN = { overview: "Overview", roadmap: "Roadmap", work: "Work", docs: "Docs", shells: "Sessions", launch: "Sessions", device: "Device", decisions: "Decisions" };
const STATE_BADGE = { "Waiting for you": "mark", Stopped: "dim", "Not started": "dim" };

function seenFrom(route) {
  const q = route.query;
  const path = { issues: "work", prs: "work", actions: "work", queue: "work", notes: "docs" }[route.path] || route.path;
  const tab = route.path === "work" ? q.tab || "issues" : route.path;
  // From the address, which a link can fill with anything. Same pattern as hubd's.
  const item = (repo, n) => (/^[A-Za-z0-9._-]+$/.test(repo || "") && /^[0-9]+$/.test(n || "") ? `${repo}#${n}` : null);
  if (path === "work" && item(q.at || q.repo, q.item)) return { screen: "Work", kind: SEEN_KIND[tab] || null, selection: item(q.at || q.repo, q.item) };
  if (path === "launch" && item(q.repo, q.number)) return { screen: "Sessions", kind: null, selection: item(q.repo, q.number) };
  return { screen: SEEN_SCREEN[path] || "Overview", kind: null, selection: null };
}

function keptRail() {
  try { return localStorage.getItem("steward-rail") !== "open"; } catch { return true; }
}

function StewardSession({ state, seen, buttons, reload, asks }) {
  const act = useAct(reload);
  const [note, setNote] = useState("");
  const words = state.state;
  const running = words !== "Not started" && words !== "Stopped";
  const thisItem = seen.selection ? `${seen.kind || "item"} ${seen.selection}` : "";
  const offered = (buttons || []).filter((b) => b.screen === seen.screen && (seen.selection || !b.text.includes("{selection}")) && (!b.kinds || b.kinds.includes(seen.kind)));
  const send = (b) => act.run(async () => {
    const r = await post("agents/press", { name: STEWARD, button: b.id, kind: seen.kind, selection: seen.selection });
    setNote(r.sent ? `Sent: ${b.label}` : `Queued: ${b.label}. It goes when the turn ends.`);
  });
  if (!running) {
    return html`<div class="stack" style="gap: 12px; padding: 14px">
      <p style="font-size: 14.5px">${words === "Stopped" ? "The session has stopped. Resuming continues the same conversation." : "One long-lived session for the whole project. Every write it tries asks you first, on a card."}</p>
      <${Err} text=${act.error} />
      <button class="primary" style="align-self: flex-start" disabled=${act.busy} onClick=${() => act.run(() => (words === "Stopped" ? post("agents/resume", { name: STEWARD }) : post("agents/run", { action: "project-steward" })))}>${act.busy ? "Starting…" : words === "Stopped" ? "Resume the Steward" : "Start the Steward"}</button></div>`;
  }
  const mine = asks.open.filter((a) => a.session === STEWARD);
  const offers = asks.work.items.filter((i) => i.by === STEWARD && nwWaits(i));
  return html`<div class="dock-session">
    ${mine.length > 0 && html`<div class="dock-asks stack" style="gap: 8px">${mine.map((a) => html`<${Ask} key=${a.id} ask=${a} compact onDone=${asks.reload} />`)}</div>`}
    ${offers.length > 0 && html`<div class="dock-asks stack" style="gap: 8px"><span class="eyebrow">Waiting for you</span>${offers.map((i) => html`<${WorkWaiting} key=${i.id} item=${i} compact reload=${asks.reload} />`)}</div>`}
    <div class="dock-term"><${TerminalView} key=${STEWARD} name=${STEWARD} quiet onGone=${reload} /></div>
    <div class="row" style="gap: 6px; padding: 8px 12px 0">
      ${offered.map((b) => html`<button class="dock-msg" disabled=${act.busy} title=${b.text.replaceAll("{selection}", thisItem)} onClick=${() => send(b)}>${b.label}</button>`)}
      <button class="dock-msg" title="Stops the turn, and anything queued for after it" disabled=${act.busy} onClick=${() => act.run(async () => { await post("agents/interrupt", { name: STEWARD }); setNote("Sent Esc."); })}>Esc</button></div>
    <div role="status" class="small soft" style="padding: 4px 12px 8px; min-height: 28px">${state.queued > 0 ? `${count(state.queued, "message")} queued until the turn ends, with the prompt empty. If it has ended, clear what's typed there. After Esc in the terminal, press Esc here too.` : note.startsWith("Queued") ? "" : note}</div>
    <${Err} text=${act.error || state.lost} /></div>`;
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
  const planFromSteward = () => planWork({ by: STEWARD, repo: seen.selection ? seen.selection.split("#")[0] : undefined, context: seen.selection || undefined, pins: seen.selection ? [{ kind: "ref", label: seen.selection }] : undefined });
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

function Hub({ host, route, onOut }) {
  const loaded = useLoad(() => api("asks"), [], 3000);
  // A failed read keeps what we knew, or a brief hubd error would close the cards you're filling in.
  const known = useRef({ open: [], answered: [] });
  if (loaded.data) known.current = loaded.data;
  const planned = useLoad(() => api("new-work"), [], 3000);
  const knownWork = useRef({ templates: [], items: [] });
  if (planned.data) knownWork.current = planned.data;
  const decided = useLoad(() => api("decisions"), [], 5000);
  const knownDecisions = useRef({ decisions: [], holding: null });
  if (decided.data) knownDecisions.current = decided.data;
  const reloadAll = () => { loaded.reload(); decided.reload(); return planned.reload(); };
  const asks = { ...known.current, work: knownWork.current, reload: reloadAll,
    decisions: { items: knownDecisions.current.decisions, holding: knownDecisions.current.holding, reload: decided.reload, error: decided.error } };
  asks.waiting = asks.open.length + asks.work.items.filter(nwWaits).length + decisionsAsked(asks).length;
  const waiting = asks.waiting;
  const [planner, setPlanner] = useState(null);
  const [starting, setStarting] = useState(null);
  const [behind, setBehind] = useState(null); // planned work you closed while it runs
  useEffect(() => {
    const show = (e) => { setBehind(null); setPlanner({ ...e.detail, key: Date.now() }); };
    const form = (e) => setStarting({ ...e.detail, key: Date.now() });
    window.addEventListener("hub-new-work", show);
    window.addEventListener("hub-start-form", form);
    return () => { window.removeEventListener("hub-new-work", show); window.removeEventListener("hub-start-form", form); };
  }, []);
  // Links from before Work was one page, and the items a card points to.
  // The queue is a tab of Work and the notes search is a tab of Docs; their old addresses go there.
  const legacy = { issues: "issues", prs: "prs", actions: "actions", queue: "queue" }[route.path];
  const notes = route.path === "notes";
  const path = legacy ? "work" : notes ? "docs" : route.path;
  const query = legacy ? { ...route.query, tab: legacy } : notes ? { ...route.query, tab: "notes" } : route.query;
  const views = { overview: Overview, roadmap: Roadmap, work: Work, docs: Docs, shells: Sessions, launch: Launch, device: DeviceView, decisions: DecisionsPage };
  const View = views[path] || Overview;
  const here = path === "launch" ? "shells" : path;
  return html`<div class="with-dock"><div class="dock-main">
    <header class="top"><${Logo} />
      <nav aria-label="Primary">${NAV.map(([key, label]) => (key === "shells"
        ? html`<a href=${hash("shells", { tab: "needs" })} aria-current=${here === key ? "page" : null} aria-label=${waiting ? `Sessions, ${waiting} waiting for you` : null}>${label}${waiting > 0 && html`<span class="nav-count" aria-hidden="true">${waiting}</span>`}</a>`
        : html`<a href="#/${key}" aria-current=${here === key ? "page" : null}>${label}</a>`))}</nav>
      <div class="end">
        ${!host.gh && html`<span class="badge bad">no gh on the host</span>`}
        ${!host.tmux && html`<span class="badge bad">no tmux on the host</span>`}
        <${Budget} />
        <span class="mono" style="font-size: 13px">${host.user}</span>
        <button class="plain" onClick=${async () => { await post("logout"); onOut(); }}>Sign out</button>
      </div></header>
    <${View} key=${path + JSON.stringify(path === "shells" || path === "work" ? {} : query)} query=${query} asks=${asks} /></div>
    <${Steward} route=${route} asks=${asks} />
    ${planner && html`<${NewWork} key=${planner.key} open=${planner} work=${asks.work} asks=${asks} reload=${reloadAll} onClose=${(left) => { setPlanner(null); setBehind(left || null); }} />`}
    ${starting && html`<${StartForm} key=${starting.key} item=${starting} work=${asks.work} reload=${reloadAll} onClose=${() => setStarting(null)} />`}
    ${behind && html`<div role="status" class="nw-toast"><span style="flex: 1"><span class="mono" style="font-weight: 600">${behind.name}</span> runs in the background. Its drafts show up in <a href=${hash("shells", { tab: "needs" })}>Sessions › Needs you</a>.</span>
      <button class="plain" onClick=${() => planWork({ id: behind.id })}>Reopen</button><button class="square" aria-label="Dismiss" onClick=${() => setBehind(null)}>×</button></div>`}</div>`;
}

render(html`<${App} />`, document.getElementById("root"));
