# Feature Specification: Design sessions

**Feature Branch**: `spec-design-sessions`
**Created**: 2026-11-08
**Status**: Draft
**Input**: "Design sessions: the designer persona that works on the design boards in GlassineOS/ui, and the live view through which the maintainer sees the same boards as the session."

## Context

The designs of the organization's programs are canvases of boards, kept in GlassineOS/ui, one folder per project,
built on the Interleaf design system. A **design session** is a session that changes those boards to answer a
design question. The session sees each change as an image through the renderer in that repository (GlassineOS/ui
spec 003). This spec defines the **Designer** persona, the **design** action that starts one, and the **design
view**, through which the maintainer watches and clicks the same boards while the session works.

A merged design change means the design is accepted. It reaches a program through ordinary work in that
program's repository; a design session changes no program.

It uses Launch (005) for starting the session and the session view (Sessions, 004).

## User Scenarios & Testing

### User Story 1 - Answer a design question (Priority: P1)

The maintainer starts a session on an issue that asks a design question and gets a proposal to review.

**Why this priority**: This is what the persona is for.

**Independent Test**: Launch "design" on an issue in any repository and check where the session works and what
it hands back.

**Acceptance Scenarios**:

1. **Given** an issue in GlassineOS/shell asking for a new settings layout, **When** the maintainer launches
   "design" on it, **Then** the session runs in a new worktree of GlassineOS/ui on its own branch, and its result
   is a draft pull request there that changes boards in the shell's folder and links the issue.
2. **Given** a design session has changed a board, **When** it goes on, **Then** it has rendered the changed
   board and looked at the image in each voice and scheme the change can affect, and its report says which
   combinations it looked at.
3. **Given** the design question needs a change to Interleaf itself, **When** the session proposes it, **Then**
   the change is in the same pull request and passes that repository's checks.

---

### User Story 2 - Watch and try the boards live (Priority: P1)

The maintainer sees what the session is designing while it works and clicks through it.

**Why this priority**: The maintainer judges a design by eye, and steering a session early saves rounds.

**Independent Test**: Open the design view of a running design session, change a board, click a prototype.

**Acceptance Scenarios**:

1. **Given** a running design session, **When** the maintainer opens its design view, **Then** they see the
   canvas of the session's worktree, rendered on the host, with a voice, scheme and pen picker.
2. **Given** the design view is open, **When** the session saves a board, **Then** the view shows the change
   within two seconds without a reload by the maintainer.
3. **Given** an interactive board in the design view, **When** the maintainer clicks and types in it, **Then** it
   reacts as its logic says.
4. **Given** the session wants to show a board, **When** it opens that board in the design view, **Then** the
   maintainer sees that board, in that voice, scheme, pen and size, if the view is on follow.

---

### User Story 3 - Review a design change (Priority: P2)

The maintainer reviews a finished design proposal.

**Why this priority**: Reviewing needs only the pull request, which already exists without this spec; the
persona's report makes it quicker.

**Independent Test**: Read the pull request of a finished design session.

**Acceptance Scenarios**:

1. **Given** a finished design session, **When** the maintainer opens its pull request, **Then** it names each
   changed board, says what question each answers, and lists the implementation work a merge would call for.

### Edge Cases

- The design view is open and the session ends: the view stays usable until the maintainer closes it or the
  worktree is removed.
- The renderer crashes or a board hangs: the view says so and offers a restart; the session is not affected.
- Two viewers open the same design view: both see the same view; either can click.
- A board tries to reach the network or to run code against the hub: it fails like in any render, and the hub is
  not affected.
- A session that is not a design session has no design view.

## Requirements

Each requirement is one testable statement. A requirement of another spec is cited with the spec's name and
number, as in "Launch (005) FR-012".

### Functional Requirements

#### The Designer

- **FR-001**: The persona library has a Designer whose instructions say: work only on boards and on Interleaf;
  use Interleaf's tokens and components and its guidelines rather than local values; render every changed board
  and look at the image before going on; try each voice and scheme the change can affect and the e-ink scheme
  always; keep the boards a new proposal replaces out of the result unless a comparison was asked for; never
  publish outside the repository.
- **FR-002**: The action library has a **design** action: persona Designer, result pr, for issues, in the sense
  of Launch (005) FR-012.
- **FR-003**: A design session's worktree is in GlassineOS/ui whichever repository its issue is in. This is the
  one exception to Launch (005) FR-009.
- **FR-004**: The action's ceiling lets the session run the renderer and its checks without asking.
- **FR-005**: A design session's pull request names the changed boards, the question each answers and the
  implementation work that would follow; it files none of that work itself.

#### The design view

- **FR-010**: Every design session has a design view, opened from its session view at any of the session view's
  sizes (Sessions, 004).
- **FR-011**: The design view shows a browser running on the host, on the renderer's preview of the session's
  worktree, as a live picture, and sends the viewer's clicks, touches, scrolling and keys to it.
- **FR-012**: A board's code never runs in the hub's page or with the hub's origin, cookies or session.
- **FR-013**: The view shows the host browser's pixels unscaled at 100 %, and scaled to fit otherwise, with the
  zoom shown; e-ink schemes are judged by eye at 100 %.
- **FR-014**: The design session can open a given board, voice, scheme, pen and size in the design view. A
  viewer can turn off following and go their own way, and can turn it on again.
- **FR-015**: The session can read which board, voice, scheme, pen and size the viewer has open, so the
  maintainer can say "this one".
- **FR-016**: The design view has the access rules of a session's terminal (Sessions, 004): only the signed-in
  maintainer, from the hub's own origin.
- **FR-017**: A design view's browser starts when first opened or asked for, and stops when the session has
  ended and no viewer has been connected for ten minutes. At most three run at once; opening a fourth names the
  three and offers to stop one.
- **FR-018**: A design view's browser and preview cannot reach the network other than the preview itself.
- **FR-019**: The design view works at phone width (App frame (001) SC-003) and by keyboard for its own
  controls (App frame (001) SC-004).

### Key Entities

- **Design session**: a session started by the design action; it has a worktree of GlassineOS/ui and a design
  view.
- **Design view**: the live picture of the host browser that shows the session's boards.
- **Follow**: the state in which the design view shows what the session last opened.

## Success Criteria

- **SC-001**: From an issue, a design session returns a pull request whose changed boards pass the checks in
  GlassineOS/ui, without the maintainer starting anything beyond Launch.
- **SC-002**: A saved board change shows in an open design view within two seconds on the hub's host.
- **SC-003**: A click in the design view shows its effect within half a second on the local network.
- **SC-004**: A board that tries to read the hub's cookies or call the hub's API gets nothing.

## Assumptions

- GlassineOS/ui provides the preview, the single-board render and the checks by its spec 003.
- The hub runs on the maintainer's own machine and touches no device.
- A host browser is available to the hub, the one the renderer in GlassineOS/ui uses.

## Out of scope

- Implementing an accepted design in a program.
- Comments or marks drawn on a board in the view.
- Editing boards by hand in the view; boards are edited as files.
- A design view for sessions that are not design sessions.
