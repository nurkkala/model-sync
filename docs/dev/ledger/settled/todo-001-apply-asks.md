---
label: TODO-001-apply-asks
title: "apply asks what to do with a setting that names a model no longer served"
state: done
added: 2026-11-13 13:30:36
closed: 2026-11-13 13:34:52
priority: 1
---

*Added 2026-11-13 13:30:36 · done 2026-11-13 13:34:52.*

A setting can name a model its provider has stopped serving. On 2026-11-13 opencode's
`agents.title.model` named `ollama/qwen3:4b` after that model was removed from Ollama, and
`diff` printed a warning about it on every run. README rule 4 then said the tool checks
such settings "and never edits them", so the remedy was a hand edit in another program's
file.

#### Ruled 2026-11-13

1. **`apply` asks, on a terminal.** `diff` and `status` stay read-only and keep the
   warning. An `apply` whose stdin is no terminal prints the warning and edits no setting,
   as it did before.
2. **Three answers: replace, remove, leave.** Replace offers the models live in that run
   across the providers the consumer receives. Remove deletes the setting, so the agent
   falls back to its own default. Leave keeps the warning.
3. **A model with a table in the index draws no question.** The table says its owner
   expects the model back, so the setting gets the warning alone. No state file is needed
   and the index stays hand-kept.
4. **pi's default is edited too.** It lives in `settings.json` beside `models.json`, a
   file the index does not name. The tool backs that file up and writes it atomically, as
   it does a consumer's file. The rewrite goes through `json.dumps`, so key order survives
   and hand formatting does not.

#### Rejected

- **A flag (`apply --fix-references`) or a separate `fix` command.** Either keeps rule 4
  true by default. Either also leaves the warning unanswered by the command that printed
  it.
- **Remembering a "leave" in a state file** under `~/.local/state/model-sync/`. That is
  new state to keep, explain, and test, for a case ruling 3 already covers.
- **Asking on every run with no exemption.** A model left unpulled for weeks would draw
  the same question at every `apply`.

#### What it changed

README rules 3 and 4 were reworded: on request, the tool now also edits the settings that
name a model. `jsonc.py` had `replace_value` and no way to delete a member; removal got
`remove_member`, which handles the member's comma and a comment on its line.

#### Not in scope

- A provider that could not be reached. Its models are unknown, so no setting naming one
  is stale (README rule 1).
- Answers given on the command line (`--replace-with`, `--yes`).

**Done when** — On a terminal, `model-sync apply` asks about a stale `agents.title.model` in a test fixture and each of the three answers (replace, remove, leave) produces the file the answer describes, with a backup; with stdin not a terminal the same run prints the warning and edits no setting; a stale setting whose model has a table in the index draws the warning and no question. `make check` passes.

*2026-11-13 13:32:33 — started.* Working area: consumers/ (a Reference with repoint and drop), jsonc.remove_member, plan (stale settings), cli apply (the question).

*2026-11-13 13:34:52* — Built. `Consumer` gains `repoint`, `drop`, and `pending`; `jsonc.remove_member` deletes a member with its comma and the `//` comment that closes its line. Tried on a pseudo-terminal against a copy of a real `opencode.jsonc`: the question appears, `r` removes `agents.title.model`, and the file still parses. Two readings taken where the rulings were silent: removing an agent's sole key leaves the agent's block in place as `{ }`, and end-of-input at the question aborts the run with that consumer's file unwritten.

*2026-11-13 13:42:12* — Two readings in the note above were later ruled the other way: TODO-006-empty-block removes the block a removal empties, and TODO-007-eof-leaves makes end of input answer leave.
