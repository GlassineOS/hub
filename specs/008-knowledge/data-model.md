# Data model: Knowledge (spec 008)

Entities this spec owns, their fields, where each is stored, and how it changes state. "Today"
cites the code on `001-hub-app` at `c81fe71`; "adds" is what this spec changes. Decisions behind
each are in `research.md` (R-numbers; another spec's as `NNN Rn`).

---

## Knowledge report

A Result of type `report` with `kept: true`. Listed by `result.list(type="report", kept=true)`;
"Follow up" opens Launch with `pins: [{kind: "text", label: "<report id>: <question>"}]`.
