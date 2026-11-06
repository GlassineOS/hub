# Data model: Overview and Roadmap (spec 007)

Entities this spec owns, their fields, where each is stored, and how it changes state. "Today"
cites the code on `001-hub-app` at `c81fe71`; "adds" is what this spec changes. Decisions behind
each are in `research.md` (R-numbers; another spec's as `NNN Rn`).

---

## Device lock view (R1)

Read only: `device.status` lines (words with an age, `hubd/devices.py:329`) and
`decision.holding_view` (`decisions.py:354`). No new fields.
