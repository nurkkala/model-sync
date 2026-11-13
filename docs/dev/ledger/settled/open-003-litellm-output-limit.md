---
label: OPEN-003-litellm-output-limit
title: "Should the tool notice a LiteLLM gateway that repeats its input limit as its output limit?"
state: ruled-no
added: 2026-11-13 13:30:37
closed: 2026-11-13 13:40:54
priority: 3
---

*Added 2026-11-13 13:30:37 · ruled no 2026-11-13 13:40:54.*

The `litellm` probe takes a model's output limit from `max_output_tokens` in
`/model/info`, which holds whatever the gateway's operator typed. A gateway in use on
2026-11-13 reports `max_output_tokens` equal to `max_input_tokens` for every model, so
its index entry sets `max_output = 32768` for the provider and a smaller value for one
model. Without that override each agent would be told a model can write as many tokens as
it can read.

Nothing tells the index's owner that the override is needed. The wrong limit shows in
`status` as a plausible number.

#### Options

1. **Warn in `status`** when a `litellm` model reports equal input and output limits and
   the index sets no `max_output` for it. Nothing written to a consumer changes.
2. **Treat equal limits as unreported**, so the model is written with no output limit
   unless the index gives one. This is wrong for a model whose limits do match.
3. **Leave it.** The README names the case under Limits.

#### Recommendation

Option 1. It changes no file and points at the exact line to add. Rule no instead if the
gateway above stays the one LiteLLM provider in the index: its override is already
written, and a warning that can never fire again is code to carry for nothing. The first
second gateway is the reopening condition.

*2026-11-13 13:40:54* — Ruled no 2026-11-13. The one LiteLLM gateway in the index already carries its `max_output` override, so the warning of option 1 could not fire again. Reopen when a second `litellm` provider enters an index: that is the first moment an owner can meet the wrong limit without having been told.
