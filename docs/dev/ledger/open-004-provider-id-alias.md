---
label: OPEN-004-provider-id-alias
title: "Should a consumer be able to call a provider by another id?"
state: open
added: 2026-11-13 13:30:37
priority: 4
---

*Added 2026-11-13 13:30:37.*

A provider has one id. Its key under `[providers]` in the index is also its key under
`providers` in every consumer's file and the prefix of every `provider/model` setting.
A file that already lists the same server under another name gets a second block from
`apply`, and the two then describe one server.

Both files in use on 2026-11-13 call each provider by its index id, so nothing is broken
today.

#### Options

1. **A map on the consumer**, `ids = { ollama = "local" }`, read wherever the consumer
   looks up or creates a provider's block and wherever it reads a `provider/model`
   setting.
2. **Leave it.** Rename the block in the consumer's file to match the index, once, by
   hand.

#### Recommendation

Rule no for now. Renaming a block is a one-time edit, and the map touches every method of
every consumer. Reopen on the first file where the rename is not free: one whose other
settings, or another tool, refer to the provider by the old name.
