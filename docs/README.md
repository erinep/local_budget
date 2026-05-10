# Documentation

Project docs for Local Budget Parser. Each file owns one concern and is updated on its own cadence.

| File | Purpose | Updated |
|---|---|---|
| [architecture.md](architecture.md) | Module shape, responsibilities, principles, cross-cutting concerns | Rarely; major architectural shifts only |
| [roadmap.md](roadmap.md) | Phases, work items, exit criteria, open decisions, out of scope | As phases ship |
| [risks.md](risks.md) | Living risk register with phase mapping | When new risks surface or mitigations land |
| [orchestration.md](orchestration.md) | Agent roles, parallelism rules, merge protocol | When the orchestration model evolves |
| [adr/](adr/) | Architecture Decision Records, one per non-trivial decision | Append-only |

The orientation entry point is [`../CLAUDE.md`](../CLAUDE.md) at the repo root. Start there if you are a fresh agent or contributor; it lists the reading order.

## Conventions

- Files in this directory are **the source of truth** for the topic they own. Do not duplicate content across files; link instead.
- ADRs are append-only. Once an ADR is committed, it is not edited; if a decision is reversed, write a new ADR that supersedes the old one (and link both ways).
- Every doc is reviewable in plain markdown. Diagrams are ASCII or Mermaid, not images, so PRs render cleanly.
- Keep prose tight. Senior reader, no hand-holding. If a section needs more than a screen, it is probably two sections.
