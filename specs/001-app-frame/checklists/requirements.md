# Specification Quality Checklist: App frame

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

- [x] No [NEEDS CLARIFICATION] markers remain (maintainer, 2026-11-06: budget meter small in the header, FR-006)
- [x] Requirements are testable and unambiguous (one statement each, stable IDs FR-001 to FR-025)
- [x] Success criteria are measurable (SC-001 to SC-004)
- [x] Success criteria are technology-agnostic
- [x] All acceptance scenarios are defined (1 scenario, Given/When/Then)
- [x] Edge cases are identified (hubd unreachable, a usage reading that is not known, wide content at phone width)
- [x] Scope is clearly bounded (Out of scope section)
- [x] Dependencies and assumptions identified (Context names the specs it depends on;
  Contracts table; Implementation notes list missing backend)

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria (Acceptance section)
- [x] User scenarios cover the primary flows of this part
- [x] No implementation details leak into the specification body

## Constitution check

- [x] Contracts: owned and consumed interfaces listed with version rule
- [x] Tests at the right level: host tests via `make check`; browser check by hand
- [x] Security boundary: credentials stay in hubd (FR-021), policy fails closed
  (FR-022), only the maintainer's login records a decision (FR-023), agent text never
  widens rights (FR-024)
- [x] Hardware: "No device risk"; Go cards and lock display are data only
- [x] E-ink and accessibility: reduced motion, no colour-only state, outline severity

## Validation notes

- Wording pass for "currently / old vs new" language in the body: none outside
  Implementation notes.
- Cross-references to other specs carry the spec number.
