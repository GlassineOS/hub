/* GlassineOS hub — shared mock data for every current board.
   One source of truth: screens and components read window.HUB and never define their own copies. */
window.HUB = {
  user: 'maintainer',
  layers: ['STRATEGY', 'KNOWLEDGE & RULES', 'DISTRIBUTION', 'SYSTEM', 'HARDWARE ENABLEMENT'],
  repos: [
    { name: 'hub', layer: 'STRATEGY', issues: 14, prs: 3, runs: 'pppppppppp', last: '2 h ago', release: 'unreleased', commit: 'hubd: refuse gh api --input paths', labels: [['strategic', 9], ['hub', 5]] },
    { name: 'docs', layer: 'KNOWLEDGE & RULES', issues: 19, prs: 2, runs: 'pppppppppr', last: '12 min ago', release: 'site live', commit: 'guides: EDL recovery draft', labels: [['guide', 11], ['hardware', 6], ['fix', 2]] },
    { name: 'interleaf', layer: 'KNOWLEDGE & RULES', issues: 7, prs: 1, runs: 'pppppppppp', last: 'yesterday', release: 'v1.0.0', commit: 'stationery: focus ring on leather', labels: [['a11y', 4], ['tokens', 3]] },
    { name: 'image-builder', layer: 'DISTRIBUTION', issues: 8, prs: 2, runs: 'pppppppfff', last: '41 min ago', release: 'none', commit: 'build: add binfmt setup step', labels: [['ci', 5], ['rootfs', 3]] },
    { name: 'packages', layer: 'DISTRIBUTION', issues: 6, prs: 1, runs: 'pppppppppp', last: '3 days ago', release: 'repo 2026.10', commit: 'shell: bump to 0.6.0', labels: [['packaging', 4], ['bug', 2]] },
    { name: 'shell', layer: 'SYSTEM', issues: 38, prs: 5, runs: 'ppppppfppp', last: '1 h ago', release: 'v0.6.0', commit: 'quick settings: voice picker', labels: [['ui', 17], ['bug', 13], ['voice', 8]] },
    { name: 'ink-input', layer: 'SYSTEM', issues: 14, prs: 3, runs: 'pppppppppp', last: '3 h ago', release: 'v0.3.2', commit: 'pen: predictive smoothing', labels: [['latency', 7], ['bug', 5]] },
    { name: 'reader', layer: 'SYSTEM', issues: 11, prs: 1, runs: 'pppppppppp', last: '3 weeks ago', release: 'v0.2.0', commit: 'epub: fix hyphenation', labels: [['feature', 6], ['bug', 5]] },
    { name: 'kernel', layer: 'HARDWARE ENABLEMENT', issues: 31, prs: 6, runs: 'ppfppppppr', last: '18 min ago', release: 'none', commit: 'drm/epd: add waveform LUT loader', labels: [['bug', 14], ['driver', 11], ['dts', 6]] },
    { name: 'epd', layer: 'HARDWARE ENABLEMENT', issues: 9, prs: 0, runs: 'pppppppppp', last: '4 days ago', release: 'none', commit: 'lut: header parser', labels: [['driver', 5], ['bug', 4]] },
    { name: 'firmware', layer: 'HARDWARE ENABLEMENT', issues: 6, prs: 0, runs: 'pppppppppp', last: '6 days ago', release: 'none', commit: 'readme: licence status of blobs', labels: [['licence', 3], ['waveform', 3]] }
  ],
  unplaced: ['epd-experiments'],
  totals: { issues: 163, prs: 25, failing: 'image-builder, shell', docsIndex: 'building' },

  /* Items: issues, pull requests, workflow runs, roadmap items. partOf = the “Part of …” line in the body. */
  items: {
    'hub#44': { kind: 'roadmap', title: 'EPD waveform driver', status: 1, partOf: null, linked: [['kernel', 2, 6], ['firmware', 1, 2], ['epd', 0, 2]], who: 'maintainer', target: 'Dec 2026' },
    'hub#41': { kind: 'roadmap', title: 'Mainline kernel boots to framebuffer', status: 1, linked: [['kernel', 5, 7], ['boot', 3, 3]], who: 'maintainer', target: 'Dec 2026' },
    'hub#47': { kind: 'roadmap', title: 'EDL recovery path, documented', status: 2, linked: [['boot', 4, 4], ['docs', 2, 3]], who: 'docs-edl', target: 'Dec 2026' },
    'hub#52': { kind: 'roadmap', title: 'Pen input latency under 20 ms', status: 1, linked: [['ink-input', 2, 5], ['shell', 1, 4]], who: 'maintainer', target: 'Mar 2027' },
    'hub#55': { kind: 'roadmap', title: 'Interleaf voices in the shell', status: 2, linked: [['shell', 3, 6], ['interleaf', 4, 4]], who: 'maintainer', target: 'Mar 2027' },
    'hub#60': { kind: 'roadmap', title: 'Reproducible images built in CI', status: 0, linked: [['image-builder', 0, 4], ['packages', 1, 3]], who: 'unassigned', target: 'Jun 2027' },
    'hub#63': { kind: 'roadmap', title: 'docs.glassine.org v1', status: 0, linked: [['docs', 3, 12]], who: 'unassigned', target: 'Jun 2027' },
    'hub#36': { kind: 'roadmap', title: 'Hub: first private push after review', status: 3, linked: [['hub', 6, 6]], who: 'maintainer', target: 'Nov 2026' },

    'kernel#212': { kind: 'pr', title: 'drm/epd: add waveform LUT loader', state: 'REVIEWED', icon: 'r', age: '3h', group: 'NEEDS YOU', branch: 'agent/kernel-lut → main', size: '+412 −38', partOf: 'kernel#204', author: 'maintainer via kernel-lut', threads: 3,
      body: 'Loads waveform tables from /lib/firmware and selects a mode by panel temperature.', checks: [['build · arm64', 'p', '6m 12s'], ['checkpatch', 'p', '41s'], ['dt-validate', 'p', '1m 03s'], ['boot-test · qemu', 'r', '2m so far'], ['sign-off', 'p', '1s']],
      files: [['drivers/gpu/drm/epd/epd_lut.c', 288, 0], ['drivers/gpu/drm/epd/epd_core.c', 64, 31], ['drivers/gpu/drm/epd/epd_lut.h', 41, 0], ['Documentation/devicetree/bindings/display/epd.yaml', 12, 4]] },
    'shell#301': { kind: 'pr', title: 'Voice picker in quick settings', state: 'READY', icon: 'p', age: '1d', group: 'NEEDS YOU', branch: 'feat/voice-picker → main', size: '+188 −41', partOf: 'hub#55', author: 'maintainer', body: 'Adds White, Editorial and Stationery switching with their pens.', checks: [['build', 'p', '2m 40s'], ['ui-snapshots', 'p', '1m 15s']], files: [] },
    'image-builder#40': { kind: 'pr', title: 'Add binfmt setup for aarch64 rootfs', state: 'FAILING', icon: 'f', age: '41m', group: 'NEEDS YOU', branch: 'agent/investigate-1184 → main', size: '+12 −0', partOf: 'image-builder#37', author: 'maintainer via investigate-1184', body: 'Registers qemu-aarch64 with binfmt_misc before debootstrap’s second stage.', checks: [['lint', 'p', '12s'], ['build-image', 'f', '9m 01s'], ['size-report', 'w', 'skipped']], files: [] },
    'docs#88': { kind: 'pr', title: 'Guide: recover a Note Air over EDL', state: 'DRAFT', icon: 'o', age: '12m', group: 'FROM AGENT SESSIONS', branch: 'agent/docs-edl → main', size: '+214 −3', partOf: 'hub#47', author: 'maintainer via docs-edl', body: 'Adds the EDL recovery guide.', checks: [['mkdocs build --strict', 'p', '48s']], files: [] },
    'ink-input#57': { kind: 'pr', title: 'Predictive smoothing for pen strokes', state: 'OPEN', icon: 'p', age: '2d', group: 'EVERYTHING ELSE', branch: 'pen/predict → main', size: '+96 −12', partOf: 'hub#52', author: 'input-team', body: 'Cuts perceived latency from 34 ms to 22 ms on the bench.', checks: [['build', 'p', '1m 02s']], files: [] },

    'epd#9': { kind: 'issue', title: 'LUT loader rejects version 0', state: 'OPEN', icon: 'o', age: '4d', group: 'NEEDS YOU', partOf: 'hub#44', labels: ['driver'], assignee: 'unassigned', body: 'Version 0 is reserved in hardware/epd/waveforms.md, but the header check accepts it.' },
    'epd#11': { kind: 'issue', title: 'Release the firmware buffer on every error path', state: 'OPEN', icon: 'o', age: '4d', group: 'NEEDS YOU', partOf: 'hub#44', labels: ['bug'], assignee: 'unassigned', body: 'request_firmware() succeeds but the buffer leaks when parsing fails.' },
    'firmware#18': { kind: 'issue', title: 'Waveform blobs: redistribution licence', state: 'BLOCKED', icon: 'o', age: '6d', group: 'NEEDS YOU', partOf: 'hub#44', labels: ['licence'], assignee: 'maintainer', body: 'Need a written statement before any blob enters the repository.' },
    'kernel#204': { kind: 'issue', title: 'Waveform LUT loader', state: 'OPEN', icon: 'o', age: '2w', group: 'IN SESSIONS', partOf: 'hub#44', labels: ['driver'], assignee: 'maintainer', body: 'Load and validate waveform tables.' },
    'kernel#219': { kind: 'issue', title: 'Temperature compensation for LUT selection', state: 'OPEN', icon: 'o', age: '1d', group: 'IN SESSIONS', partOf: 'hub#44', labels: ['driver'], assignee: 'unassigned', body: 'Split out of kernel#204.' },
    'docs#91': { kind: 'issue', title: 'Verify Note Air partition table', state: 'OPEN', icon: 'o', age: '1d', group: 'IN SESSIONS', partOf: 'hub#47', labels: ['hardware'], assignee: 'unassigned', body: 'Every hardware fact needs a verification date.' },
    'image-builder#37': { kind: 'issue', title: 'rootfs step fails on arm64 runners', state: 'OPEN', icon: 'o', age: '1d', group: 'IN SESSIONS', partOf: 'hub#60', labels: ['ci'], assignee: 'unassigned', body: 'debootstrap second stage: exec format error.' },
    'shell#288': { kind: 'issue', title: 'Quick settings: brightness slider skips steps', state: 'OPEN', icon: 'o', age: '3d', group: 'UNTRIAGED', partOf: null, labels: ['bug', 'ui'], assignee: 'unassigned', body: 'The slider maps 0–100 onto 16 panel steps unevenly.' },
    'reader#20': { kind: 'issue', title: 'Crash on PDFs with JBIG2 images', state: 'OPEN', icon: 'o', age: '9h', group: 'UNTRIAGED', partOf: null, labels: [], assignee: 'unassigned', body: 'Segfault in the PDF backend.' },

    'build-image #1184': { kind: 'run', title: 'image-builder · build-image', state: 'FAILED', icon: 'f', age: '41m', group: 'FAILED', repo: 'image-builder', trigger: 'push to main · a3f91c2', runner: 'ubuntu-24.04-arm', duration: '9m 01s', body: 'Step “rootfs” exited 1: exec format error.', checks: [['checkout', 'p', '3s'], ['deps', 'p', '1m 20s'], ['rootfs', 'f', '7m 32s'], ['pack', 'w', 'skipped']] },
    'ci #902': { kind: 'run', title: 'kernel · ci', state: 'RUNNING', icon: 'r', age: 'now', group: 'RUNNING', repo: 'kernel', trigger: 'pull request kernel#212', runner: 'ubuntu-24.04-arm', duration: '14m so far', body: 'Boot test running in qemu.', checks: [['build', 'p', '6m 12s'], ['qemu boot', 'r', '2m so far']] },
    'deploy #455': { kind: 'run', title: 'docs · deploy', state: 'PASSED', icon: 'p', age: '2h', group: 'RECENT', repo: 'docs', trigger: 'push to main', runner: 'ubuntu-24.04', duration: '1m 48s', body: 'Published docs.glassine.org at a41c09e.', checks: [['build', 'p', '48s'], ['publish', 'p', '22s']] }
  },

  /* Sessions: one session covers one or more items; no item is special. */
  sessions: {
    'steward': { persona: 'Steward', model: 'claude-sonnet-5-5', state: 'WAITING', covers: [], origin: 'always on', cwd: '~/src/glassine/hub', mode: 'default · hub writes ask', steward: true,
      lines: [['you', '› start a session to implement epd#9 and epd#11'], ['tool', '● hub.get_issue(epd#9) · hub.get_issue(epd#11)'], ['out', 'Same file, same error path — one session.'], ['tool', '● hub.suggest_session(action="implement", issues=["epd#9","epd#11"])'], ['ask', '◆ suggested a session — waiting for you'], ['you', '› where does hub#44 stand?'], ['tool', '● hub.search_issues("Part of GlassineOS/hub#44")'], ['out', 'kernel#212 has the loader; temperature compensation needs an issue.'], ['ask', '◆ asked to create kernel#219 — waiting for you']] },
    'kernel-lut': { persona: 'Kernel engineer', model: 'claude-opus-5-5', state: 'WAITING', covers: ['kernel#204', 'kernel#219'], prs: ['kernel#212'], origin: 'Work · kernel#212 · address review', branch: 'agent/kernel-lut', cwd: '~/hub-worktrees/kernel/agent-kernel-lut', mode: 'default · asks before edits', view: 'embedded',
      lines: [['dim', '# hub started kernel-lut · Kernel engineer · covers kernel#204, kernel#219'], ['tool', '● hub.get_pr(kernel#212) · 3 review threads'], ['tool', '● hub.search("epd waveform LUT versions") → 3 passages'], ['out', '● Fixing thread epd_lut.c:88 — reject version 0'], ['ask', '? waiting for permission to edit epd_lut.c']] },
    'review-kernel-212': { persona: 'Code reviewer', model: 'claude-opus-5-5', state: 'DONE', covers: ['kernel#212'], origin: 'Work · kernel#212 · review', cwd: '~/hub-worktrees/kernel/review-212', mode: 'plan · read-only',
      lines: [['tool', '● hub.get_pr(kernel#212)'], ['out', '● Posted 3 review threads and a summary'], ['dim', '  finished after 18 min']] },
    'docs-edl': { persona: 'Docs writer', model: 'claude-opus-5-5', state: 'WAITING', covers: ['hub#47', 'docs#91'], prs: ['docs#88'], origin: 'Work · hub#47 · draft docs', branch: 'agent/docs-edl', cwd: '~/hub-worktrees/docs/agent-docs-edl', mode: 'accept edits',
      lines: [['tool', '● hub.get_issue(hub#47)'], ['tool', '● hub.search("enter EDL mode Note Air") → 6 passages'], ['out', '● mkdocs build --strict passed'], ['ask', '? waiting for permission to git push']] },
    'investigate-1184': { persona: 'CI investigator', model: 'claude-opus-5-5', state: 'WAITING', covers: ['build-image #1184', 'image-builder#37'], prs: ['image-builder#40'], origin: 'Work · build-image #1184', branch: 'agent/investigate-1184', cwd: '~/hub-worktrees/image-builder/agent-investigate-1184', mode: 'default',
      lines: [['tool', '● hub.get_run_log(build-image #1184, failed=true)'], ['out', '● binfmt_misc has no qemu-aarch64 entry'], ['out', '● Opened image-builder#40'], ['ask', '? asks which fix to use']] },
    'audit-hub': { persona: 'Security auditor', model: 'claude-fable-5-1', state: 'DONE', covers: [], repo: 'hub', origin: 'Overview · hub · security audit', cwd: '~/hub-worktrees/hub/audit-hub', mode: 'plan · read-only', view: 'background',
      lines: [['tool', '● Read hubd/auth.py · hubd/proxy/argv.py · hubd/server.py'], ['find', '◆ HIGH · session token compared with =='], ['done', '✓ 4 drafts ready · 31 min']] },
    'arch-kernel': { persona: 'Architect', model: 'claude-opus-5-5', state: 'RUNNING', covers: [], repo: 'kernel', origin: 'Overview · kernel · architecture audit', cwd: '~/hub-worktrees/kernel/arch-kernel', mode: 'plan · read-only', view: 'background',
      lines: [['tool', '● Read decisions/ · 9 records'], ['tool', '● Glob drivers/gpu/drm/epd/** → 14 files'], ['dim', '  mapping module boundaries… 12 min']] },
    'triage-weekly': { persona: 'Triage', model: 'claude-sonnet-5-5', state: 'DONE', covers: ['shell#288', 'reader#20'], origin: 'Steward · weekly', cwd: '~/src/glassine/hub', mode: 'default',
      lines: [['tool', '● hub.list_issues(untriaged, 7 days) → 6'], ['done', '✓ 5 label changes ready']] },
    'maintainer': { plain: true, persona: 'Shell', model: '', state: 'ATTACHED', covers: [], origin: 'you', cwd: '~/src/glassine/hub',
      lines: [['you', '$ python -m pytest -q'], ['out', '133 passed, 2 skipped']] }
  },

  /* Everything waiting on you. Kinds: permission, question, suggestion, results. Count = the Sessions badge. */
  interactions: [
    { id: 'i1', kind: 'question', session: 'steward', steward: true, waited: '14 min', timeoutLeft: 'until you answer', timeoutPct: 100, header: 'SCOPE · 0.3',
      question: 'hub#60 needs the arm64 runner the kernel boot tests use. What should 0.3 include?', note: '← I’d move it: 0.3 is about the kernel path.',
      options: [{ label: 'Move hub#60 to 0.5', desc: 'Frees the runner for kernel boot tests.', rec: true }, { label: 'Keep it, add a second runner', desc: 'New self-hosted runner and its review.' }, { label: 'Split it', desc: 'CI images now, reproducibility in 0.5.' }], links: ['hub#60', 'hub#44'] },
    { id: 'i2', kind: 'permission', session: 'steward', steward: true, tool: 'hub.create_issue', waited: '3 min', timeoutLeft: '7:00', timeoutPct: 70, title: 'Create an issue in kernel',
      code: 'hub.create_issue(repo="kernel",\n  title="Temperature compensation for LUT selection",\n  body="… Part of GlassineOS/hub#44")', reason: 'kernel#212 merged without it; splitting it out keeps hub#44 honest.', alwaysLabel: 'hub.create_issue' },
    { id: 'i3', kind: 'suggestion', session: 'steward', steward: true, waited: '1 min', what: 'session', action: 'implement', covers: ['epd#9', 'epd#11'],
      title: 'Implement epd#9 + epd#11 in one session', why: 'Both are in epd_lut.c and touch the same error path. One session avoids two branches conflicting.',
      notes: 'Do epd#9 first: reject version 0 in the header check. epd#11 touches the same error path, so fix it in the same branch with its own commit. One PR that closes both.' },
    { id: 'i4', kind: 'suggestion', session: 'steward', steward: true, waited: '40 min', what: 'new work', action: 'sec', repo: 'hub',
      title: 'Security audit of hub', why: 'LAN mode (hub#74) is next, and the last audit predates the tool server.', notes: 'Assume LAN clients can reach the dashboard. Focus on token handling, TLS setup and the tool server.' },
    { id: 'i5', kind: 'permission', session: 'docs-edl', tool: 'Bash', waited: '6 min', timeoutLeft: '4:02', timeoutPct: 40, title: 'Run a command', code: 'git push -u origin agent/docs-edl', reason: 'Push the guide branch so the draft PR docs#88 updates.', alwaysLabel: 'git push' },
    { id: 'i6', kind: 'question', session: 'investigate-1184', waited: '3 min', timeoutLeft: '7:10', timeoutPct: 72, header: 'CI FIX',
      question: 'The runner image has no qemu-user-static. Which fix should image-builder#40 use?', options: [{ label: 'docker/setup-qemu-action', desc: 'Maintained action; registers binfmt for every architecture.', rec: true }, { label: 'Install qemu-user-static in the job', desc: 'One apt step; adds about 20 s per run.' }] },
    { id: 'i7', kind: 'permission', session: 'kernel-lut', tool: 'Edit', waited: '40 s', timeoutLeft: '9:20', timeoutPct: 93, title: 'Edit a file', path: 'drivers/gpu/drm/epd/epd_lut.c · line 88',
      diff: [['−', 'if (hdr->version > EPD_LUT_VERSION_MAX)'], ['+', 'if (!hdr->version || hdr->version > EPD_LUT_VERSION_MAX)'], ['', '        return -EINVAL;']], reason: 'Review thread epd_lut.c:88 — version 0 is reserved.', alwaysLabel: 'edits in this worktree' },
    { id: 'i8', kind: 'results', session: 'audit-hub', waited: '2 h', action: 'sec', repo: 'hub', title: 'Security audit of hub · 4 drafts', summary: '1 HIGH · 1 MEDIUM · 1 LOW · 1 INFO — “hubd: session token compared with ==” and 3 more.' },
    { id: 'i9', kind: 'results', session: 'triage-weekly', waited: '5 h', action: 'triage', repo: 'shell', covers: ['shell#288', 'reader#20'], title: 'Weekly triage · 5 label changes', summary: 'Adds labels to 4 issues and a “Part of hub#55” line to shell#288.' }
  ],

  /* Agent actions. result = what the Result stage shows. */
  actions: {
    review: { label: 'Review', persona: 'Code reviewer', model: 'claude-opus-5-5', mode: 'plan · read-only', result: 'comment', eta: '10–20 min', for: ['pr'], query: 'review conventions', ceiling: 'Read and comment. Never merge, close or push.' },
    address: { label: 'Address review', persona: 'Kernel engineer', model: 'claude-opus-5-5', mode: 'default · asks before edits', result: 'pr', eta: '15–30 min', for: ['pr'], query: 'review threads fixups', ceiling: 'This PR’s branch only. No merge.' },
    fix: { label: 'Fix checks', persona: 'CI fixer', model: 'claude-opus-5-5', mode: 'default', result: 'pr', eta: '10–20 min', for: ['pr'], query: 'CI setup', ceiling: 'This PR’s branch only. No merge.' },
    implement: { label: 'Implement', persona: 'Engineer', model: 'claude-opus-5-5', mode: 'default · asks before edits', result: 'pr', eta: '20–60 min', for: ['issue'], query: 'design notes conventions', ceiling: 'Own branch, draft PR. No merge, no dispatch.' },
    triage: { label: 'Triage', persona: 'Triage', model: 'claude-sonnet-5-5', mode: 'default', result: 'labels', eta: '2–5 min', for: ['issue'], query: 'labelling rules', ceiling: 'Proposes labels and Part of lines; you apply them.' },
    investigate: { label: 'Investigate', persona: 'CI investigator', model: 'claude-opus-5-5', mode: 'default', result: 'findings', eta: '10–20 min', for: ['run'], query: 'runner images caching', ceiling: 'Own branch; rerun only on ask.' },
    issue: { label: 'Issue', persona: 'Issue writer', model: 'claude-sonnet-5-5', mode: 'default · drafts only', result: 'drafts', eta: '2–5 min', for: ['new'], query: 'similar issues', ceiling: 'Writes nothing; you file the draft.' },
    sec: { label: 'Security audit', persona: 'Security auditor', model: 'claude-fable-5-1', mode: 'plan · read-only', result: 'drafts', eta: '20–40 min', for: ['new', 'repo'], query: 'hubd token verification gh proxy refusals', ceiling: 'Read-only checkout. Cannot write code, file issues or post.' },
    arch: { label: 'Architecture audit', persona: 'Architect', model: 'claude-opus-5-5', mode: 'plan · read-only', result: 'drafts', eta: '20–40 min', for: ['new', 'repo'], query: 'decision records module boundaries', ceiling: 'Read-only. Proposes, never refactors.' },
    road: { label: 'Roadmap item', persona: 'Steward', model: 'claude-sonnet-5-5', mode: 'default · drafts only', result: 'drafts', eta: '5–10 min', for: ['new', 'roadmap'], query: 'roadmap overlap', ceiling: 'Drafts the item, its child issues and board column. You file them.' },
    docs: { label: 'Docs gap sweep', persona: 'Docs writer', model: 'claude-sonnet-5-5', mode: 'plan · read-only', result: 'drafts', eta: '10–20 min', for: ['new', 'repo'], query: 'guides index coverage', ceiling: 'Read-only. Drafts issues in docs only.' },
    deps: { label: 'Dependency review', persona: 'Release steward', model: 'claude-sonnet-5-5', mode: 'plan · read-only', result: 'drafts', eta: '5–10 min', for: ['new', 'repo'], query: 'dependency policy upgrades', ceiling: 'Read-only. Upgrades are separate sessions.' }
  },
  models: [['claude-fable-5-1', 'Fable'], ['claude-opus-5-5', 'Opus'], ['claude-sonnet-5-5', 'Sonnet'], ['claude-haiku-5-5', 'Haiku']],
  plannerModels: [['claude-opus-5-5', 'Opus'], ['claude-sonnet-5-5', 'Sonnet'], ['claude-haiku-5-5', 'Haiku']],

  /* Example results per result type. */
  results: {
    drafts: {
      sec: [['HIGH', 'hubd: session token compared with == (timing leak)', 'Use hmac.compare_digest. Evidence: hubd/auth.py:57.', 'hub', 'security', 'hub#70'], ['MEDIUM', 'gh proxy: short flag -h slips past the --hostname refusal', 'Normalise short flags first. Evidence: hubd/proxy/argv.py:31.', 'hub', 'security', 'hub#70'], ['LOW', 'Unix socket is 0660 for a moment before chmod 0600', 'Create it with umask 077. Evidence: hubd/server.py:12.', 'hub', 'security', 'hub#70'], ['INFO', 'No rate limit on the tool server’s token checks', 'Loopback only today; needed before LAN mode.', 'hub', 'security, lan', 'hub#74']],
      arch: [['', 'Split github.py into REST and GraphQL clients', 'Paging and errors differ; one module mixes both.', 'hub', 'architecture', ''], ['', 'Decision record 0010: where session state lives', 'hubd owns it; app and tmux only read.', 'hub', 'decision', '']],
      issue: [['', 'ink-input: stroke latency doubles in battery saver', 'From ~22 ms to ~45 ms when battery saver lowers the poll rate. Steps to reproduce in the body.', 'ink-input', 'bug, latency', 'hub#52']],
      road: [['', 'Offline docs on the device', 'Ship a docs snapshot with each image; open it from the shell.', 'hub', 'strategic', ''], ['', 'docs: build an offline bundle in CI', 'Static export plus the search index.', 'docs', 'build', 'the new item'], ['', 'image-builder: include the docs bundle', 'Under /usr/share/glassine/docs.', 'image-builder', 'packaging', 'the new item']],
      docs: [['', 'Document the voice picker in quick settings', 'Shipped in shell 0.6.0; not in the guides.', 'docs', 'guide', 'hub#55']],
      deps: [['', 'pyyaml 6.0.1 → 6.0.2', 'Security fix, no API change.', 'hub', 'deps, security', '']]
    },
    pr: { title: 'epd: reject LUT version 0 and release the buffer on error', size: '+38 −9 · 2 commits', checks: [['build · arm64', 'p'], ['checkpatch', 'p'], ['boot-test · qemu', 'r']] },
    comment: { summary: 'The loader shape is right. Three things before merge: reject version 0, release the firmware buffer on error, update the binding example.', notes: [['epd_lut.c:88', 'Version 0 is reserved; reject it.'], ['epd_lut.c:142', 'Buffer leaks on this error path.'], ['epd.yaml:12', 'Example doesn’t exercise waveform-name.']] },
    labels: [['shell#288', 'add label', 'ui'], ['shell#288', 'add “Part of hub#55”', ''], ['reader#20', 'add label', 'bug'], ['reader#20', 'add label', 'pdf'], ['ink-input#61', 'add label', 'bug']],
    findings: { summary: 'The arm64 runner image has no qemu-user-static, so debootstrap’s second stage can’t run foreign binaries.', fix: 'Register binfmt with docker/setup-qemu-action before the rootfs step.' }
  },

  passages: {
    review: [['hardware/epd/waveforms.md', '0.84', 'the LUT format'], ['kernel/CONTRIBUTING.md#review', '0.70', 'review checklist']],
    address: [['hardware/epd/waveforms.md#versions', '0.86', 'v0 is reserved'], ['kernel/CONTRIBUTING.md#fixups', '0.72', 'fixup commits']],
    fix: [['infra/runners.md', '0.78', 'runner images']],
    implement: [['hardware/epd/waveforms.md#versions', '0.86', 'v0 is reserved'], ['decisions/0005-firmware-loading.md', '0.79', 'release rules for request_firmware']],
    triage: [['process/labels.md', '0.83', 'labelling rules'], ['process/roadmap.md#strategic', '0.77', 'which issues are strategic']],
    investigate: [['infra/runners.md', '0.79', 'ARM runner images'], ['image-builder/README.md#rootfs', '0.74', 'second stage under qemu-user']],
    issue: [['process/labels.md', '0.81', 'labelling rules']],
    sec: [['decisions/0003-rights-vs-interface.md', '0.88', 'rights live in hubd'], ['hub/security/gh-proxy.md#refusals', '0.84', 'what the proxy must refuse'], ['hub/security/tokens.md', '0.79', 'token issue and check']],
    arch: [['decisions/', '0.83', 'every decision record']],
    road: [['process/roadmap.md#strategic', '0.82', 'what makes an item strategic']],
    docs: [['style/content.md', '0.80', 'content rules']],
    deps: [['process/release.md#deps', '0.78', 'upgrade policy']]
  }
};

/* Review threads, past sessions and workspace rows (Work item, Sessions › History). */
window.HUB.threads = {
  'kernel#212': [
    { id: 't1', who: 'reviewer-a', where: 'epd_lut.c:88', text: 'Version 0 is reserved — this check lets it through.', open: true, fix: 'session kernel-lut is on it (waiting for your OK to edit)' },
    { id: 't2', who: 'reviewer-a', where: 'epd_lut.c:141', text: 'request_firmware() buffer leaks when the header parse fails.', open: true, fix: 'same root cause as epd#11' },
    { id: 't3', who: 'reviewer-b', where: 'epd.yaml:22', text: 'Binding needs an example with temperature ranges.', open: true, fix: '' },
    { id: 't4', who: 'reviewer-a', where: 'epd_core.c:40', text: 'Nit: use dev_err_probe().', open: false, fix: 'fixed in 3c1e0aa' }
  ]
};
window.HUB.history = [
  ['kernel-lut-v1', 'Kernel engineer', 'Opus', 'kernel#204', 'interrupted', 'Ended 3 days ago · host restarted', 'Halfway through the LUT version check; tests not run yet.', '86 turns', 'a41f…9c2e', 'kept'],
  ['review-kernel-212', 'Code reviewer', 'Opus', 'Work · kernel#212', 'finished', 'Finished 3 hours ago', 'Posted one summary comment and 3 inline notes on kernel#212.', '40 turns', '5d02…b1e9', 'kept'],
  ['audit-hubd', 'Security auditor', 'Fable', 'Overview · hub', 'finished', 'Finished 9 days ago', 'Wrote 3 draft findings; you filed hub#70–72.', '142 turns', '7be0…11d4', 'removed'],
  ['shell-288', 'Engineer', 'Opus', 'shell#288', 'ended', 'Ended by you 2 days ago', 'Rounding fix drafted; you stopped it to triage first.', '54 turns', 'c93a…0f71', 'kept'],
  ['triage-weekly-w44', 'Triage', 'Sonnet', 'Steward · weekly', 'finished', 'Finished 8 days ago', 'Labelled 14 issues, suggested 3 “Part of” lines.', '31 turns', '19dd…a2b8', 'none']
];
window.HUB.worktrees = [
  ['rv', '~/hub-worktrees/kernel/review-212', 'detached checkout · session review-kernel-212 finished', 'safe', 2.3, 'git -C ~/src/glassine/kernel worktree remove ~/hub-worktrees/kernel/review-212'],
  ['s288', '~/hub-worktrees/shell/agent-shell-288', 'agent/shell-288 · no commits ahead of main', 'safe', 0.64, 'git -C ~/src/glassine/shell worktree remove ~/hub-worktrees/shell/agent-shell-288\ngit -C ~/src/glassine/shell branch -d agent/shell-288'],
  ['tmux', 'tmux -L glassine-hub · 2 dead sessions', 'review-kernel-212, triage-weekly · exited', 'safe', 0, 'tmux -L glassine-hub kill-session -t review-kernel-212\ntmux -L glassine-hub kill-session -t triage-weekly'],
  ['ah', '~/hub-worktrees/hub/audit-hub', 'detached checkout · results not handled yet (Needs you)', 'review', 0.18, '# results are still waiting in Needs you — handle them first, then:\ngit -C ~/src/glassine/hub worktree remove ~/hub-worktrees/hub/audit-hub'],
  ['klv1', '~/hub-worktrees/kernel/agent-kernel-lut-v1', 'agent/kernel-lut-v1 · 2 commits not pushed', 'review', 1.9, '# 2 commits not pushed — this will fail on purpose:\ngit -C ~/src/glassine/kernel branch -d agent/kernel-lut-v1'],
  ['ci', '~/hub-worktrees/image-builder/agent-investigate-1184', 'PR image-builder#40 open', 'keep', 1.4, ''],
  ['kl', '~/hub-worktrees/kernel/agent-kernel-lut', 'session kernel-lut is running', 'inuse', 2.1, ''],
  ['edl', '~/hub-worktrees/docs/agent-docs-edl', 'session docs-edl is running', 'inuse', 0.09, '']
];

/* Knowledge: one search over docs, ingested work items and (planned) code, plus research reports. */
window.HUB.actions.research = { label: 'Research', persona: 'Researcher', model: 'claude-opus-5-5', mode: 'plan · read-only', result: 'report', eta: '5–15 min', for: ['new', 'knowledge'], query: 'knowledge', ceiling: 'Read-only. Searches every index, reads files and threads; writes only its report.' };
window.HUB.passages.research = [['guides/recovery/edl.md#enter-edl-mode', '0.86', 'the documented recovery path'], ['docs#91 · comment by reviewer-a', '0.81', 'the partition offsets are still unverified'], ['kernel/drivers/gpu/drm/epd/epd_lut.c:72', '0.64', 'where the LUT header is parsed']];
window.HUB.results.report = {
  answer: [
    'A Note Air that won’t boot after flashing is recoverable over EDL as long as XBL is intact: the guide’s steps work, and ABL can be replaced because XBL accepts test-key-signed images.',
    'Two things are not settled. The partition offsets the guide uses come from source and are unverified (docs#91 is open for that). And kernel#212’s LUT loader changes nothing in this path; the earlier suspicion in hub#47 that a bad LUT bricks the panel was ruled out in a review thread.'
  ],
  sources: [['DOC', 'guides/recovery/edl.md', 'steps and the 05c6:9008 check'], ['DOC', 'hardware/note-air/boot-chain.md#abl', 'why ABL can be replaced'], ['ISSUE', 'docs#91', 'offsets still unverified'], ['PR', 'kernel#212 · thread t2', 'LUT loader is not in the boot path'], ['CODE', 'kernel/arch/arm64/boot/dts/note-air.dts:41', 'partition node the offsets come from']],
  gaps: ['No one has restored abl_a from a backup on real hardware.', 'The guide doesn’t say what to do if lsusb shows nothing at all.'],
  followups: [['issue', 'Draft an issue for each gap'], ['docs', 'Sweep docs for other unverified hardware facts']]
};
window.HUB.knowledge = {
  domains: [
    { id: 'docs', label: 'Docs', state: 'BUILDING', detail: 'docs.glassine.org · deploy #456 is indexing 7e2d3f1; search answers from a41c09e', count: '412 passages', status: 'exists' },
    { id: 'work', label: 'Work items', state: 'CURRENT', detail: 'issues, PRs, review threads and comments of 11 repos · last ingest 14 min ago', count: '1,284 items', status: 'exists' },
    { id: 'code', label: 'Code', state: 'PLANNED', detail: 'main branch of each repo, chunked by symbol · not indexed yet; results below are illustrative', count: '—', status: 'proposed' }
  ],
  defaultQuery: 'tablet won’t boot after flashing, how do I get it back',
  corpus: [
    { d: 'docs', kind: 'DOC', ref: 'guides/recovery/edl.md#enter-edl-mode', title: 'Recover a Note Air over EDL', repo: 'docs', snip: 'Hold both volume keys while connecting USB. The tablet shows nothing; lsusb lists 05c6:9008 when it is in EDL.', score: 0.86, meta: 'guide · verified 2026-10-12', terms: 'tablet boot flash recover recovery edl brick usb note air' },
    { d: 'work', kind: 'ISSUE', ref: 'docs#91', title: 'Verify Note Air partition table', repo: 'docs', snip: 'reviewer-a: offsets in partitions.md come from the DTS, nobody has read them off a device yet.', score: 0.81, meta: 'open · comment 1 of 4 · 1 d ago', open: true, terms: 'partition flash boot recover offsets verify note air' },
    { d: 'docs', kind: 'DOC', ref: 'hardware/note-air/boot-chain.md#abl', title: 'Boot chain', repo: 'docs', snip: 'XBL accepts an ABL signed with the public test keys, so a broken ABL can be replaced without touching XBL.', score: 0.79, meta: 'hardware · verified 2026-09-30', terms: 'tablet boot chain abl xbl flash recover signed' },
    { d: 'work', kind: 'PR', ref: 'docs#88', title: 'Guide: recover a Note Air over EDL', repo: 'docs', snip: 'Adds the EDL recovery guide. Draft from session docs-edl; waits for docs#91.', score: 0.77, meta: 'draft · from docs-edl · 12 min ago', open: true, terms: 'recover edl guide boot flash note air' },
    { d: 'docs', kind: 'DOC', ref: 'guides/install/backup.md', title: 'Back up partitions before flashing', repo: 'docs', snip: 'Read out boot_a, boot_b and abl_a first. Restoring them is the way back from a failed flash.', score: 0.74, meta: 'guide', terms: 'tablet backup flash partitions restore boot recover' },
    { d: 'code', kind: 'CODE', ref: 'kernel/arch/arm64/boot/dts/note-air.dts:41', title: 'partitions { … } node', repo: 'kernel', snip: 'abl_a: partition@6000000 { label = "abl_a"; reg = <0x0 0x6000000 0x0 0x100000>; };', score: 0.69, meta: 'dts · main @ 9f1e2aa', terms: 'partition abl boot flash dts offsets note air' },
    { d: 'work', kind: 'ISSUE', ref: 'hub#47', title: 'EDL recovery path, documented', repo: 'hub', snip: 'Roadmap item. Session docs-edl covers it together with docs#91.', score: 0.66, meta: 'roadmap · in review', open: true, terms: 'edl recovery roadmap boot docs' },
    { d: 'code', kind: 'CODE', ref: 'kernel/drivers/gpu/drm/epd/epd_lut.c:72', title: 'epd_lut_parse_header()', repo: 'kernel', snip: 'if (hdr->version > EPD_LUT_MAX_VERSION) return -EINVAL; /* version 0 slips through */', score: 0.52, meta: 'c · branch agent/kernel-lut', terms: 'lut waveform version header parse epd firmware' },
    { d: 'work', kind: 'PR', ref: 'kernel#212', title: 'drm/epd: add waveform LUT loader', repo: 'kernel', snip: 'reviewer-a on epd_lut.c:141 — request_firmware() buffer leaks when the header parse fails.', score: 0.49, meta: 'reviewed · thread t2', open: true, terms: 'lut waveform loader firmware leak epd kernel review' },
    { d: 'docs', kind: 'DOC', ref: 'hardware/epd/waveforms.md#versions', title: 'Waveform table versions', repo: 'docs', snip: 'Version 0 is reserved by the controller and must be rejected.', score: 0.47, meta: 'hardware', terms: 'lut waveform version epd reserved' },
    { d: 'docs', kind: 'DOC', ref: 'hardware/note-air/dead-ends.md#fastboot', title: 'Dead ends: fastboot unlock', repo: 'docs', snip: 'The bootloader refuses unlock on retail units; EDL is the only verified path.', score: 0.61, meta: 'hardware', terms: 'fastboot unlock bootloader boot recover dead ends' },
    { d: 'work', kind: 'ISSUE', ref: 'image-builder#37', title: 'rootfs step fails on arm64 runners', repo: 'image-builder', snip: 'debootstrap second stage: exec format error. Needs qemu-user-static or binfmt.', score: 0.31, meta: 'open · in session investigate-1184', open: true, terms: 'ci rootfs arm64 qemu binfmt image build exec format error' },
    { d: 'code', kind: 'CODE', ref: 'image-builder/.github/workflows/build-image.yml:58', title: 'job rootfs · step debootstrap', repo: 'image-builder', snip: 'run: sudo debootstrap --arch=arm64 --foreign bookworm rootfs', score: 0.3, meta: 'yaml · main @ a3f91c2', terms: 'ci rootfs arm64 debootstrap workflow image build exec format error foreign' },
    { d: 'work', kind: 'ISSUE', ref: 'shell#288', title: 'Quick settings: brightness slider skips steps', repo: 'shell', snip: 'The slider maps 0–100 onto 16 panel steps unevenly.', score: 0.22, meta: 'closed · fixed in shell#310', open: false, terms: 'brightness slider quick settings shell ui' }
  ],
  reports: [
    { q: 'Which hardware facts in the docs are still unverified?', when: 'yesterday', model: 'Opus', sources: '14 sources', by: 'you', session: 'research-unverified' },
    { q: 'What blocks reproducible images (hub#60)?', when: '4 days ago', model: 'Sonnet', sources: '9 sources', by: 'the Steward', session: 'research-hub60' }
  ]
};

/* Scale: the project has dozens of repositories. Every repo choice in the design must work at this size. */
(function () {
  const more = [
    ['rfcs', 'STRATEGY', 4, 1, 'pppppppppp', '5 days ago', 'n/a', 'rfc-0007: offline docs'],
    ['website', 'KNOWLEDGE & RULES', 5, 1, 'pppppppppp', '2 days ago', 'live', 'home: new screenshots'],
    ['translations', 'KNOWLEDGE & RULES', 12, 3, 'pppppppfpp', '6 h ago', 'n/a', 'nb: quick settings strings'],
    ['design-assets', 'KNOWLEDGE & RULES', 2, 0, 'pppppppppp', '3 weeks ago', 'n/a', 'icons: pen pressure glyph'],
    ['ota-server', 'DISTRIBUTION', 9, 2, 'pppppppppp', '1 day ago', 'v0.4.1', 'delta: verify signatures first'],
    ['mirror', 'DISTRIBUTION', 3, 0, 'pppppppppp', '2 weeks ago', 'n/a', 'rsync: bandwidth cap'],
    ['installer', 'DISTRIBUTION', 7, 1, 'ppppfppppp', '4 days ago', 'v0.2.0', 'edl: detect 05c6:9008'],
    ['ci-images', 'DISTRIBUTION', 4, 1, 'ppppppppff', '3 h ago', 'n/a', 'arm64: add qemu-user-static'],
    ['notes', 'SYSTEM', 22, 4, 'pppppppppp', '2 h ago', 'v0.5.0', 'notebooks: lasso select'],
    ['sketch', 'SYSTEM', 9, 2, 'pppppppppp', '1 day ago', 'v0.1.3', 'brush: pressure curve'],
    ['launcher', 'SYSTEM', 6, 1, 'pppppppppp', '5 days ago', 'v0.3.0', 'grid: e-ink friendly paging'],
    ['settings', 'SYSTEM', 10, 2, 'pppppppppp', '1 day ago', 'v0.4.0', 'wifi: hidden networks'],
    ['sync-daemon', 'SYSTEM', 15, 3, 'pppfpppppp', '7 h ago', 'v0.2.4', 'webdav: retry with backoff'],
    ['wifi-agent', 'SYSTEM', 5, 0, 'pppppppppp', '2 weeks ago', 'v0.1.1', 'wpa: country code'],
    ['voice', 'SYSTEM', 8, 2, 'pppppppppp', '9 h ago', 'v0.2.0', 'tts: Interleaf voices'],
    ['keyboard', 'SYSTEM', 11, 1, 'pppppppppp', '3 days ago', 'v0.3.1', 'layouts: Norwegian'],
    ['boot', 'HARDWARE ENABLEMENT', 4, 1, 'pppppppppp', '1 week ago', 'n/a', 'abl: test-key signing notes'],
    ['u-boot', 'HARDWARE ENABLEMENT', 6, 1, 'pppppppppp', '2 weeks ago', 'n/a', 'note-air: env in mmc'],
    ['touch-driver', 'HARDWARE ENABLEMENT', 7, 1, 'pppppppppp', '5 days ago', 'none', 'gt9xx: palm rejection'],
    ['wacom-pen', 'HARDWARE ENABLEMENT', 5, 2, 'pppppppppr', '30 min ago', 'none', 'tilt: report in hid'],
    ['battery-fw', 'HARDWARE ENABLEMENT', 3, 0, 'pppppppppp', '1 month ago', 'none', 'fuel gauge: profile v2']
  ];
  more.forEach(([name, layer, issues, prs, runs, last, release, commit]) => window.HUB.repos.push({ name, layer, issues, prs, runs, last, release, commit, labels: [] }));
  window.HUB.recentRepos = ['kernel', 'epd', 'docs', 'image-builder'];
  Object.assign(window.HUB.items, {
    'epd#12': { kind: 'issue', title: 'Reject LUT tables shorter than the header says', state: 'OPEN', icon: 'o', age: '2d', group: 'BACKLOG', partOf: 'hub#44', labels: ['driver'], assignee: 'unassigned', body: 'The parser trusts hdr->len; a truncated blob reads past the buffer.' },
    'epd#14': { kind: 'issue', title: 'Temperature ranges overlap in waveform table', state: 'OPEN', icon: 'o', age: '1w', group: 'BACKLOG', partOf: 'hub#44', labels: ['bug'], assignee: 'unassigned', body: 'Two modes claim 18–20 °C; selection depends on table order.' },
    'kernel#221': { kind: 'issue', title: 'epd: use dev_err_probe() in the probe path', state: 'OPEN', icon: 'o', age: '3h', group: 'BACKLOG', partOf: 'kernel#204', labels: ['cleanup'], assignee: 'unassigned', body: 'Split out of a review nit on kernel#212.' },
    'firmware#19': { kind: 'issue', title: 'Record a checksum for every waveform blob', state: 'CLOSED', icon: 'p', age: '3w', group: 'BACKLOG', partOf: 'hub#44', labels: ['licence'], assignee: 'maintainer', body: 'Done in firmware#20.' }
  });
})();

/* Notes: the read-only view of `notes find` — notes, old docs, diaries, memory files, past transcripts.
   Agents read and add to the same notes with the notes command; this page only searches. */
window.HUB.notes = {
  defaultQuery: 'lut version',
  sources: ['notes', 'diaries', 'old docs', 'memory files', 'transcripts'],
  warnings: ['3 transcripts skipped: permission denied (~/.claude/projects/-home-maintainer-hub-worktrees-audit-hub)', 'memory files: 2 files skipped, not valid UTF-8 (memory/agents/old/*.bin)'],
  rows: [
    { st: 'current', src: 'notes/epd/waveforms.md', label: 'c12', text: 'Waveform table version 0 is reserved by the controller. The loader must reject it with -EINVAL before reading the mode table; kernel#212 does this since 3c1e0aa.' },
    { st: 'current', src: 'notes/epd/waveforms.md', label: 'c14', text: 'The LUT header length is authoritative only after the magic and version checks pass. Read it once, then bound every later read by it.' },
    { st: 'open', src: 'notes/epd/open-questions.md', label: 'q3', text: 'Does firmware 2.1 ship any table with version 0x02, or only 0x01? Nobody has dumped a 2.1 blob yet; this decides whether the loader needs a 0x02 path before 0.3.' },
    { st: 'current', src: 'transcripts/kernel-lut/2026-11-03T16-12.jsonl', label: '', text: 'Session kernel-lut confirmed on hardware: with version 0 rejected, the panel keeps the last good table and refreshes normally. Recorded by the session with notes add --claim c12 --evidence.' },
    { st: 'retracted', src: 'notes/epd/waveforms.md', label: 'c9', text: 'A bad LUT can brick the panel permanently. — Retracted 2026-10-28: the controller falls back to its ROM table on any parse error; the “brick” was a dead FPC cable (see hub#47 thread).' },
    { st: 'history', src: 'diaries/2026-10-21.md', label: '', text: 'Spent the evening on LUT versions. Version byte seems to be at offset 4, not 2 as the vendor PDF says. Will check against a second blob tomorrow.' },
    { st: 'history', src: 'notes/epd/waveforms.md', label: 'c7', text: 'LUT version byte is at offset 2. — Superseded by c11 (offset 4), measured on two blobs.' },
    { st: 'unreviewed', src: 'old-docs/hardware/epd-notes-2025.txt', label: '', text: 'From the 2025 notes: “tables above version 3 use a different temperature encoding”. No source given, and nobody on the project has seen a version 3 table.' },
    { st: '', src: 'memory/agents/researcher/lut.md', label: '', text: 'LUT tables are always 4096 bytes.' },
    { st: 'open', src: 'notes/kernel/review.md', label: 'q7', text: 'Should the loader log every rejected table at warn level, or only the first per boot? reviewer-a prefers once per boot; no decision recorded.' },
    { st: 'current', src: 'notes/ci/arm64.md', label: 'c31', text: 'The arm64 runners have no binfmt handlers by default. debootstrap --foreign needs qemu-user-static registered first, which is why build-image #1184 failed with “exec format error”.' },
    { st: 'unreviewed', src: 'transcripts/audit-hubd/2026-10-27T09-40.jsonl', label: '', text: 'The auditor guessed that tmux socket permissions are 0770, but did not check. Kept as an unreviewed transcript excerpt. ' + 'It goes on to compare the hub socket with the default tmux socket under /tmp, lists which processes could connect if the mode were wider, walks through what an attacker on the same host could do with an attached session, and suggests three mitigations — a private socket directory, an explicit umask in hubd before it starts tmux, and a check at login that refuses to attach when the mode is wrong. Each mitigation is followed by a long discussion of how to test it on the device, what the hub would show in Sessions when the check fails, and why none of this has been verified against the running system yet. '.repeat(4) }
  ],
  more: 40, limit: 340
};

/* Notes upkeep: compaction and the docs sweep. Both are started by hand, for all notes or one topic. */
Object.assign(window.HUB.actions, {
  compact: { label: 'Compact notes', persona: 'Archivist', model: 'claude-opus-5-5', mode: 'default · notes only', result: 'notes', eta: '10–30 min', for: ['new', 'notes'], query: 'duplicate superseded claims', ceiling: 'Changes notes only through the notes command. Never deletes; every change cites its evidence.' },
  sweep: { label: 'Sweep notes for docs', persona: 'Docs writer', model: 'claude-sonnet-5-5', mode: 'plan · read-only', result: 'drafts', eta: '10–20 min', for: ['new', 'notes'], query: 'current claims missing from docs', ceiling: 'Read-only. Drafts docs issues; a docs PR is its own session.' }
});
window.HUB.passages.compact = [['notes/epd/waveforms.md', '0.91', '14 claims, 3 likely duplicates'], ['diaries/2026-10-21.md', '0.77', 'offset measurements not yet in a claim'], ['transcripts/kernel-lut/2026-11-03T16-12.jsonl', '0.72', 'hardware confirmation of c12']];
window.HUB.passages.sweep = [['notes/epd/waveforms.md#c12', '0.88', 'current, not in any guide'], ['hardware/epd/waveforms.md', '0.84', 'the docs page these belong on'], ['guides/recovery/edl.md', '0.63', 'still repeats retracted c9']];
window.HUB.results.notes = [
  ['merge', 'c7 + c11 → c11', 'c7 “version byte is at offset 2” · c11 “version byte is at offset 4”', 'c11 stays current; c7 becomes history, pointing to c11', 'two blob dumps in diaries/2026-10-21.md and 2026-10-22.md'],
  ['distil', 'new claim c15', '5 diary lines and 2 transcript excerpts about the header length', 'c15 (current): “The header length is valid only after the magic and version checks.”', '7 source lines, all cited in the claim'],
  ['answer', 'q3 → c16', 'q3 (open): does firmware 2.1 ship version 0x02 tables?', 'c16 (current): “Firmware 2.1 ships only version 0x01.” q3 closed, pointing to c16', 'transcripts/kernel-lut/2026-11-04T10-02.jsonl · blob dump'],
  ['supersede', 'c9 wording', 'c9 (retracted) has no pointer to what replaced it', 'c9 stays retracted; adds “see c17: falls back to ROM table”', 'hub#47 review thread'],
  ['status', 'memory/agents/researcher/lut.md', 'no status: “LUT tables are always 4096 bytes.”', 'retracted: blobs of 3072 and 6144 bytes exist', 'firmware#19 checksum list'],
  ['flag', 'old-docs/hardware/epd-notes-2025.txt', 'archive, unreviewed: “version 3 uses a different temperature encoding”', 'left as is · needs a human: no source and no counter-evidence', '—']
];
window.HUB.results.drafts.sweep = [
  ['HIGH', 'EDL guide still says a bad LUT can brick the panel', 'guides/recovery/edl.md repeats c9, retracted on 2026-10-28. Replace it with c17: the controller falls back to its ROM table.', 'docs', 'fix · hardware', 'hub#47'],
  ['MEDIUM', 'Waveform page gives the version byte at offset 2', 'hardware/epd/waveforms.md contradicts current c11 (offset 4, measured on two blobs). Both versions quoted in the issue.', 'docs', 'fix · hardware', 'hub#44'],
  ['LOW', 'Document how the loader rejects version 0', 'c12 and c16 are current and in no guide. Proposed section for hardware/epd/waveforms.md with their evidence dates.', 'docs', 'guide · hardware', 'hub#44'],
  ['INFO', 'Known unknowns: temperature encoding above version 3', 'Unreviewed archive note with no source. Listed under “Not known yet” on the waveform page, never as a fact.', 'docs', 'guide', 'hub#44']
];
window.HUB.notes.totals = { entries: '1,912', claims: 214, open: 11, unreviewed: 37, nostatus: 9, sinceCompact: 126, lastCompact: '19 days ago', lastSweep: '5 weeks ago' };
window.HUB.notes.topics = [
  { path: 'notes/epd/', claims: 48, open: 3, unreviewed: 6, nostatus: 2, since: 31, last: '12 days ago' },
  { path: 'notes/kernel/', claims: 37, open: 4, unreviewed: 2, nostatus: 1, since: 22, last: '19 days ago' },
  { path: 'notes/ci/', claims: 21, open: 1, unreviewed: 0, nostatus: 3, since: 18, last: 'never' },
  { path: 'notes/hub/', claims: 29, open: 2, unreviewed: 4, nostatus: 0, since: 9, last: '19 days ago' },
  { path: 'notes/input/', claims: 16, open: 1, unreviewed: 1, nostatus: 1, since: 6, last: '2 months ago' },
  { path: 'diaries/ · transcripts/', claims: 0, open: 0, unreviewed: 24, nostatus: 2, since: 40, last: 'never' }
];
window.HUB.results.notesCmds = [
  'notes merge c7 --into c11',
  'notes add --topic epd --status current --cite diaries/2026-10-21.md:12 --cite transcripts/kernel-lut/2026-11-03T16-12.jsonl:88 "The header length is valid only after the magic and version checks."',
  'notes answer q3 --with "Firmware 2.1 ships only version 0x01." --cite transcripts/kernel-lut/2026-11-04T10-02.jsonl:41',
  'notes supersede c9 --by c17',
  'notes status memory/agents/researcher/lut.md retracted --cite firmware#19',
  '# flagged for you: old-docs/hardware/epd-notes-2025.txt — no command'
];

/* Personas: every session shows its persona as an icon on a family tint, so roles are visible at a glance.
   Family colour groups roles (build, review, investigate, write, organise); the icon tells personas within a family apart. */
window.HUB.families = {
  build: { label: 'builds', tint: '#d6e2ff' },
  review: { label: 'reviews', tint: '#eadcff' },
  investigate: { label: 'investigates', tint: '#ffd9b8' },
  write: { label: 'writes', tint: '#d4efdc' },
  organise: { label: 'organises', tint: '#e2e2e2' },
  steward: { label: 'orchestrates', tint: '#ffffff' },
  shell: { label: 'plain shell', tint: '#ffffff' }
};
window.HUB.personas = {
  'Engineer': { family: 'build', icon: 'M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z' },
  'Kernel engineer': { family: 'build', icon: 'M7 7h10v10H7zM10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4' },
  'CI fixer': { family: 'build', icon: 'M14 4l6 6-3 3-6-6zM11 7l-8 8v3h3l8-8' },
  'Code reviewer': { family: 'review', icon: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4M8 11l2 2 4-4' },
  'CI investigator': { family: 'investigate', icon: 'M3 12h4l2-6 4 12 2-6h6' },
  'Security auditor': { family: 'investigate', icon: 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6zM9 12l2 2 4-4' },
  'Architect': { family: 'investigate', icon: 'M4 20L12 4l8 16M7 14h10' },
  'Docs writer': { family: 'write', icon: 'M4 20l4-1 11-11-3-3L5 16zM14 6l3 3' },
  'Issue writer': { family: 'write', icon: 'M5 21V4h11l-2 4 2 4H5' },
  'Researcher': { family: 'write', icon: 'M4 19V5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2zM8 7h7' },
  'Archivist': { family: 'write', icon: 'M3 4h18v4H3zM5 8v12h14V8M10 12h4' },
  'Triage': { family: 'organise', icon: 'M3 12V4h8l10 10-8 8zM7.5 7.5h.01' },
  'Release steward': { family: 'organise', icon: 'M3 7l9-4 9 4v10l-9 4-9-4zM3 7l9 4 9-4M12 11v10' },
  'Steward': { family: 'steward', icon: '' },
  'Shell': { family: 'shell', icon: 'M4 6l6 6-6 6M12 18h8' }
};
/* A reviewer running on the PR that docs-edl implements, so two sessions share an item. */
window.HUB.sessions['review-docs-88'] = { persona: 'Code reviewer', model: 'claude-opus-5-5', state: 'RUNNING', covers: ['docs#88'], origin: 'Work · docs#88 · review', cwd: '~/hub-worktrees/docs/review-88', mode: 'plan · read-only',
  lines: [['dim', '# hub started review-docs-88 · Code reviewer · covers docs#88'], ['tool', '● hub.get_pr(docs#88) · +214 −3'], ['tool', '● hub.search("EDL recovery steps verified") → 4 passages'], ['out', '● Step 3 cites partitions.md offsets that docs#91 has not verified yet'], ['out', '● Drafting the summary comment…']] };

/* Direct GitHub actions (things you do yourself, through the hub's gh proxy). Agents never get merge, close or cancel. */
window.HUB.items['kernel#212'].labels = ['driver', 'epd'];
window.HUB.items['kernel#212'].behind = 3;
window.HUB.items['kernel#212'].approved = false;
window.HUB.labelSet = ['bug', 'driver', 'epd', 'firmware', 'hardware', 'cleanup', 'docs', 'ci', 'security', 'good first issue'];
window.HUB.workflows = {
  'image-builder': [['build-image.yml', 'Build image', ['ref', 'board: note-air|tab-ultra', 'publish: false']], ['nightly.yml', 'Nightly', ['ref']]],
  'kernel': [['ci.yml', 'CI', ['ref']], ['boot-test.yml', 'Boot test (qemu)', ['ref', 'config: glassine_defconfig']]],
  'docs': [['deploy.yml', 'Deploy docs', ['ref']]]
};
window.HUB.diffs = {
  'kernel#212': [
    { file: 'drivers/gpu/drm/epd/epd_lut.c', add: 288, del: 0, hunks: [
      ['@@ -0,0 +84,12 @@ static int epd_lut_parse_header(const struct firmware *fw)', [
        [' ', 84, '\tconst struct epd_lut_hdr *hdr = (const void *)fw->data;'],
        [' ', 85, ''],
        [' ', 86, '\tif (fw->size < sizeof(*hdr))'],
        [' ', 87, '\t\treturn -EINVAL;'],
        ['+', 88, '\tif (hdr->version > EPD_LUT_MAX_VERSION)'],
        ['+', 89, '\t\treturn -EINVAL;'],
        ['+', 90, '\tif (le32_to_cpu(hdr->len) > fw->size)'],
        ['+', 91, '\t\treturn -EINVAL;']]]] , thread: 't1' },
    { file: 'drivers/gpu/drm/epd/epd_core.c', add: 64, del: 31, hunks: [] },
    { file: 'drivers/gpu/drm/epd/epd_lut.h', add: 41, del: 0, hunks: [] },
    { file: 'Documentation/devicetree/bindings/display/epd.yaml', add: 12, del: 4, hunks: [] }
  ]
};
window.HUB.logs = {
  'build-image #1184': ['##[group]Run sudo debootstrap --arch=arm64 --foreign bookworm rootfs', 'I: Retrieving InRelease', 'I: Validating Packages', 'I: Extracting base-files…', 'I: Running second stage', 'chroot: failed to run command ‘/debootstrap/debootstrap’: Exec format error', '##[error]Process completed with exit code 1.']
};
