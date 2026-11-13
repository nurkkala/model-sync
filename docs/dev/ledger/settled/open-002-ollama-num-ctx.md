---
label: OPEN-002-ollama-num-ctx
title: "Should an Ollama model's context be the window Ollama serves?"
state: ruled
added: 2026-11-13 13:30:37
closed: 2026-11-13 13:40:54
priority: 2
---

*Added 2026-11-13 13:30:37 · ruled 2026-11-13 13:40:54.*

The `ollama` probe reads a model's context from `/api/show`: the `<architecture>.context_length`
key of `model_info`. That number is the most the model supports. Ollama serves the window
set by `num_ctx`, which may be smaller, so a consumer's file can claim 262144 tokens for a
model that is loaded with far fewer.

*Unverified:* what the agent sees when it sends more than the served window. The README
states the mismatch under Limits; nobody has measured the consequence here.

Today's remedy is a `context` value in the model's table in the index, typed by hand.

#### Options

1. **Read `num_ctx` where `/api/show` reports it.** A model whose Modelfile sets the
   parameter carries it in the `parameters` text of the same answer the probe already
   fetches. This costs no extra request. It misses a window set by the server's default
   or by the request.
2. **Add a provider key, `context`,** that caps every model of the provider, as
   `max_output` does for the output limit. One line in the index covers a server run with
   one window for everything.
3. **Leave it.** The per-model `context` override stays the remedy.

#### Recommendation

Measure first: load one model, read the window Ollama reports for it while loaded, and
compare that with what `status` prints. If the two agree on this machine, rule no. If
they differ, build option 2, since the server's default is the case option 1 cannot see.
The answer flips to option 1 if models here carry their own `num_ctx` in a Modelfile.

*2026-11-13 13:39:19* — Measured on Ollama 0.40.16 with nothing set in the environment. `qwen3.8:27b-mlx` was loaded with a one-token request through `/api/generate`; `ollama ps` and `/api/ps` both gave its running window as 131072, while `status` prints 262144 from `/api/show`. So the two differ on this machine by a factor of 2. None of the 3 pulled models carries `num_ctx` in the `parameters` text of `/api/show`, so option 1 would have changed nothing here. `/api/ps` reports the running window as `context_length`, for loaded models alone. Not measured: the window `gpt-oss:120b` or `flint:40b` runs with, and what an agent sees when it sends more than the running window.

*2026-11-13 13:40:54* — Ruled 2026-11-13: option 2, a provider `context` key that caps every model's window at the smaller of the cap and the reported value. Reading `/api/ps` was rejected: it is exact, and a model's entry would then change between runs with whether the model happened to be loaded. The work is TODO-005-context-cap.
