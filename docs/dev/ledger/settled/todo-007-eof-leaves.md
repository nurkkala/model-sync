---
label: TODO-007-eof-leaves
title: "End of input at apply's question answers leave"
state: done
added: 2026-11-13 13:40:54
closed: 2026-11-13 13:41:53
priority: 3
---

*Added 2026-11-13 13:40:54 · done 2026-11-13 13:41:53.*

In TODO-001-apply-asks, input ending at the question (Ctrl-D, a closed terminal) aborted
the run with exit 1. Consumers already written stayed written, and the one being asked
about lost its model-list changes along with the question.

Ruled 2026-11-13: end of input answers "leave" to that question and to every one after
it. The model lists are written for every consumer and the run exits 0. Ctrl-C still
stops the run.

Rejected: collecting every answer before writing anything. An abort would then leave
every file untouched, at the cost of moving all the questions ahead of all the writing.

The question now reads its answer with `input()`. `typer.prompt` turns both end of input
and Ctrl-C into one `Abort`, which cannot tell the two apart.

**Done when** — An `apply` on a terminal whose input ends at the first question writes every consumer's model lists, edits no setting, asks nothing further, and exits 0. `make check` passes.

*2026-11-13 13:41:53 — started.*
