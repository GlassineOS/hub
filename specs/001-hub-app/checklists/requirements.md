# Specification Quality Checklist: Hub app

**Purpose**: Check the spec is complete and of good quality before planning
**Created**: 2026-11-06
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs) outside the closing
  Implementation notes section
- [x] Focused on user value and the maintainer's needs
- [x] Written so a reader who has not seen the code can follow it
- [x] All mandatory sections completed (Context, User scenarios, Requirements, Contracts,
  Device scope and risk, Acceptance, Out of scope, Success criteria)

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain (maintainer, 2026-11-06: sessions are full
  chats, FR-027; agents merge only under an approved merge decision, FR-107a; budget meter
  small in the header, FR-086a)
- [x] Requirements are testable and unambiguous (one statement each, stable IDs FR-001 to
  FR-178)
- [x] Success criteria are measurable (SC-001 to SC-010)
- [x] Success criteria are technology-agnostic
- [x] All acceptance scenarios are defined (11 scenarios, P1 to P3, Given/When/Then)
- [x] Edge cases are identified (disabled GitHub actions with reasons, no hand-startable
  workflow, removed worktree on resume, notes tool missing/failed/limit, hubd unreachable,
  large diffs, PR head change voiding a merge decision)
- [x] Scope is clearly bounded (Out of scope section; no device actions)
- [x] Dependencies and assumptions identified (Contracts table; Implementation notes list
  missing backend)

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria (Acceptance section maps
  host tests and the browser check to requirement groups)
- [x] User scenarios cover the primary flows (answer, launch, review and merge, fix CI,
  research, Go, cleanup, phone, notes, resume, file by hand)
- [x] Feature meets the measurable outcomes in Success criteria
- [x] No implementation details leak into the specification body

## Constitution check

- [x] Security boundary: credentials stay in hubd (FR-174), policy fails closed
  (FR-175), only the maintainer's login records a decision (FR-176), agent text never
  widens rights (FR-177)
- [x] Contracts: owned and consumed interfaces listed with version rule
- [x] Tests at the right level: host tests via `make check`; browser check by hand
- [x] Hardware: "No device risk"; Go cards and lock display are data only
- [x] E-ink and accessibility: reduced motion, no colour-only state, outline severity

## Validation notes

- Iteration 1: fixed a wrong cross-reference (yellow rule), action personas checked
  against the action fixtures (triage = Triage; address commits to the PR's branch only),
  labels result includes "Part of" lines.
- Iteration 2: wording pass for "currently / old vs new" language in the body: none
  found outside Implementation notes.
- Open: the 2 clarification markers need the maintainer's answer before `/speckit.plan`.
