# Specification Quality Checklist: Needs you

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

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous (one statement each, stable IDs FR-001 to FR-022)
- [x] Success criteria are measurable (SC-001 to SC-002)
- [x] Success criteria are technology-agnostic
- [x] All acceptance scenarios are defined (2 scenarios, Given/When/Then)
- [x] Edge cases are identified (PR head change voiding a merge decision, a Go that runs out, an eye-test Go asked as "always", a request that times out)
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
- [x] Hardware: Go cards are data only; the eye-test Go is never "always"

## Validation notes

- Iteration 1: fixed a wrong cross-reference (yellow rule).
- Wording pass for "currently / old vs new" language in the body: none outside
  Implementation notes.
- Cross-references to other specs carry the spec number.
