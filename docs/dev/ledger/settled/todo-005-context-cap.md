---
label: TODO-005-context-cap
title: "A provider's context key caps the window of every model it serves"
state: done
added: 2026-11-13 13:40:54
closed: 2026-11-13 13:41:53
priority: 1
blocked_by: OPEN-002-ollama-num-ctx
---

*Added 2026-11-13 13:40:54 · done 2026-11-13 13:41:53.*

OPEN-002-ollama-num-ctx measured an Ollama server running a model with half the window the
model reports, and ruled for a provider key that caps it.

`context` on a provider is the window the server runs its models with. Each model is
written with the smaller of that number and the context it reports. A model that reports
no context gets the cap. A model's own `context` in the index is written as given, even
above the cap, since rule 2 makes the most specific index value the last word.

One reading taken where the ruling was silent: a reported input limit is held to the same
cap, so a LiteLLM model is never written with an input limit above its context. No input
limit is invented for a model that reports none.

Not in scope: reading the running window from `/api/ps`, which the ruling rejected.

**Done when** — With `context = 1000` on a provider, a model reporting 4096 is written with 1000, one reporting 512 keeps 512, one reporting nothing gets 1000, and a model's own `context` in the index still wins. The README's key table and `index.example.toml` carry the key. `make check` passes.

*2026-11-13 13:41:52 — started.*
