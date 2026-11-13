---
label: TODO-006-empty-block
title: "Removing an agent's model also removes the block it leaves empty"
state: done
added: 2026-11-13 13:40:54
closed: 2026-11-13 13:41:53
priority: 2
---

*Added 2026-11-13 13:40:54 · done 2026-11-13 13:41:53.*

TODO-001-apply-asks deleted the one member it was asked about, so removing
`agents.title.model` from an agent that held nothing else left `"title": { }` in the file.
Whether opencode accepts an empty agent block was never checked.

Ruled 2026-11-13: an agent whose model was all it held is no longer configured, so its
block goes too, and `agents` goes after its last agent. A comment inside a removed block
goes with it.

A comment on a line of its own above the removed block stays, by the rule
`jsonc.remove_member` already follows. Tried on a copy of a real file: the two-line
comment describing the title agent was left standing over nothing. Removing it would mean
guessing which comments belong to which member.

Kept as it was: a block that still holds other keys, and the top-level `model`, which has
no block of its own.

**Done when** — Removing `agents.title.model` where the model is the agent's one key deletes `title`, and deletes `agents` when that was its one agent; an agent holding other keys keeps its block. The file still parses in each case. `make check` passes.

*2026-11-13 13:41:53 — started.*
