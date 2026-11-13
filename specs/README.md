# Specs

The hub web app is specified in twelve specs. Each says what a part of the app is for and what it
must do, without naming how it is built. Requirements are cited as `NNN FR-xxx`, for example
`004 FR-008`. Plans, research and task lists are working notes for one build and are not kept
here; pull requests record how each part was built.

| Spec | What it is for | Builds on |
|---|---|---|
| [001 App frame](001-app-frame/spec.md) | The header and navigation, phone width, and the rules across all views: colours and outlines, accessibility, live updates, security and trust. | — |
| [002 Building blocks](002-building-blocks/spec.md) | The parts every view shares: item references and pickers, the repository picker, persona badges and families, session chips. | 001 |
| [003 Needs you](003-needs-you/spec.md) | Everything that waits for the maintainer, in one place: permissions, questions, decisions, suggestions and results, and the grants in force. | 001, 002 |
| [004 Sessions](004-sessions/spec.md) | Each session as a chat, what it covers and where it came from, the running sessions, history and cleanup. | 001–003 |
| [005 Launch](005-launch/spec.md) | Turning a work item into a planned session with a known result, and applying that result. | 001–004 |
| [006 Work](006-work/spec.md) | The organization's issues, pull requests and runs; one item with its details, diff, log and sessions; acting on GitHub as yourself. | 001–005 |
| [007 Overview and Roadmap](007-overview-roadmap/spec.md) | Where attention is needed across the repositories, the device lock, and progress towards the roadmap. | 001–003, 005 |
| [008 Knowledge](008-knowledge/spec.md) | Searching the documentation and work, and starting research. | 001–003, 005 |
| [009 Notes](009-notes/spec.md) | Searching and keeping up the notes sessions leave. | 001, 002, 005 |
| [010 Steward](010-steward/spec.md) | The Steward panel beside every view. | 001–005 |
| [011 Design sessions](011-design-sessions/spec.md) | The Designer persona working on the boards in GlassineOS/ui, and the live view of those boards. | 001, 004, 005 |
| [012 Workflows](012-workflows/spec.md) | State machines that sessions hold: what each step tells the agent, grants it and brings in, who decides a move, and how workflows change. | 002–005, 010, 011 |

The order of the pull requests that build these specs is tracked in GlassineOS/hub#39.
