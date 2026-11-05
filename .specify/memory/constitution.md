# GlassineOS/hub Constitution

This repository follows the GlassineOS organization principles (I–VIII). They come from
the `glassine` Spec Kit preset in `GlassineOS/.github` and are not edited per
repository. Repository-specific principles go in the last section.

## Organization principles

### I. Honest framing

GlassineOS is a hobby project, written largely with AI coding agents and not reviewed by
subsystem experts. Every README says so. Specs, plans and commit messages state what was
verified and how (host test, emulator, which device and date), and say "untested" where
it applies.

### II. Safety before features

Anything that flashes, partitions, touches the bootloader, recovery, updates or user data
states its failure mode and its escape route before it is implemented. If the escape route
depends on what the change could break, the change needs explicit maintainer approval.
Device-affecting steps never run without the maintainer's go.

### III. Nothing vendor-owned, nothing personal

No vendor firmware or binaries, device dumps, decompiler output, keys, serial numbers, MAC
addresses or local paths in any repository. Firmware comes from the user's own device at
install time. The safety scan must pass.

### IV. Contracts are owned and versioned

Every interface between repositories (protocols, file formats, configuration, D-Bus or
socket APIs) has one owning repository that specifies and versions it. Consumers pin the
version they support and adopt new versions through their own spec. Breaking changes
bump the major version.

### V. Test at the right level

Libraries and daemons test their own behaviour in their own repository (host tests, no
device needed where possible). End-to-end behaviour of the assembled system is specified
and tested only as product acceptance in the `images` repository, as high-level
behavioural scenarios on hardware, never repeating library unit tests.

### VI. Device-neutral by default

No device constants outside device packages and device configuration. Code reads device
facts from configuration so a second device needs no changes outside its own packages.

### VII. E-ink first

Every user-facing change considers refresh cost, ghosting and latency on e-ink. Animations
and continuous redraws need a reason. Latency or power trade-offs are checked by feel on
the device, not by benchmark alone.

### VIII. Upstream and licenses

Our code is GPL-2.0-or-later unless the repository says otherwise; fork commits use the
upstream license. Nothing is submitted upstream unsolicited. AI-assisted commits carry an
`Assisted-by:` or `Co-Authored-By:` trailer; agents never add `Signed-off-by`.

## Repository principles

### Security boundary

- `hubd/` runs on the host and holds every credential and host right: standard library only.
  The app and its container hold none, and reach the host only through hubd's socket.
- `hubd/ghpolicy.py` is an allowlist and fails closed. A new `gh` command or `gh api` path comes
  with its allowed and refused cases in the tests.
- What an agent reads can be an outsider's text, so nothing it says widens what it may do. A
  change that alters who can read, write or run something updates `SECURITY.md` in the same
  pull request.

### Contracts

- **Owned, not versioned yet:** the tool server's tools (names, arguments and whether they write),
  and the action library in `agents/`. Sessions outlive a hub restart, so a change must be safe for
  a session already running or resumed.
- **Internal:** the web API and hubd's socket protocol ship together and have no outside users.
- **Consumed:** the `gh` CLI, Claude Code's flags and hook events, and the docs search index from
  `GlassineOS/search`. Claude Code and `gh` aren't pinned here: what depends on their behaviour
  says so, and is tried for real.

### Tests

Every change runs `make check` and extends the tests for new behaviour. Unit tests use fakes, so
a pull request says separately what it tried for real (browser, real `claude`, real GitHub) and
what it didn't. The `sandbox` job covers the review shell, which needs real user namespaces.

### Specs

New features start with `/speckit-specify` in `specs/###-name/`. Bug fixes and small changes can
go straight to a pull request. Features merged before this constitution have no spec:
`docs/orchestrator.md` and `SECURITY.md` describe them, and they get a spec only when reworked.
An implementation that departs from its spec or design says so before it's built, not after.

### Releases and hardware

No releases yet: the hub runs from `main` on the maintainer's host. It doesn't touch devices,
and it never flashes or writes to one.

## Governance

The organization principles change only in `GlassineOS/.github` (preset version bump);
repositories pick changes up through their `.glassine/org` submodule. Repository
principles change by pull request in this repository. Cross-repository decisions are
recorded as decision records in `GlassineOS/docs`.

**Version**: 1.0.0 | **Ratified**: 2026-11-02 | **Last Amended**: 2026-11-02
