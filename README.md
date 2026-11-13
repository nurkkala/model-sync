# model-sync

A coding agent such as [pi](https://pi.dev) or [opencode](https://opencode.ai) reads the
models of a local server from a list someone typed into its configuration, and that list
goes stale the first time a model is pulled or removed. `model-sync` asks each server
which models it serves and writes the answer into every agent's file.

```sh
model-sync status   # ask every provider, show what each serves
model-sync diff     # show what apply would change in each file, writing nothing
model-sync apply    # write, keeping a backup of each file replaced
```

On a terminal, `apply` also asks what to do with a setting that names a model no longer
served: replace it with a live one, remove it, or leave it.

`diff` and `apply` take consumer names (`model-sync apply pi`) and act on every consumer
when given none. `diff --exit-code` exits 1 when any file would change.

## Terms

A **provider** is a server that serves models: an Ollama daemon, a LiteLLM gateway, a
cloud API. A **consumer** is a program whose configuration file lists models. The
**index** is the one file kept by hand, `~/.config/model-sync/index.toml`. It lists the
providers to ask and the consumer files to write, and it holds corrections to what a
provider reports.

## Rules the tool follows

1. **A model leaves a file only when its provider answered and did not list it.** A
   provider that cannot be reached (a tunnel down, a key rejected, a timeout) keeps every
   entry the file already has, and `diff` reports it as unreachable with the reason.
2. **A value in the index beats the value a provider reports.** A model the index does
   not mention still appears, with the reported values and a name made from its id.
3. **The tool owns one thing in a consumer's file: the model list of each provider in the
   index.** Every other key stays as it was, including providers the index does not list,
   with the one exception rule 4 describes. Inside an owned list the tool is the sole
   author, so a hand edit there is overwritten at the next `apply`. Put the correction in
   the index.
4. **A setting that points at a model no longer served draws a warning and blocks
   nothing.** The tool checks pi's default model and opencode's `model` and
   `agents.*.model`. `status` and `diff` report such a setting and leave it alone. So does
   `apply` when its input is no terminal. On a terminal, `apply` asks about each one (see
   [Stale settings](#stale-settings)) and edits a setting only on your answer.
5. **Nothing runs unless you run it.** There is no daemon and no schedule.

## The index

```toml
[providers.ollama]
kind = "ollama"
base_url = "http://127.0.0.1:11434"   # the server's root, without /v1
max_output = 16384                    # for every model here without its own

[providers.ollama.models."qwen3:4b"]  # optional, one table per model to correct
name = "Qwen3 4B"
max_output = 8192

[providers.gateway]
kind = "litellm"
base_url = "http://127.0.0.1:4000"
api_key = "$GATEWAY_KEY"

[consumers.pi]
kind = "pi"
path = "~/.pi/agent/models.json"

[consumers.opencode]
kind = "opencode"
path = "~/.config/opencode/opencode.jsonc"
```

A provider takes these keys:

| Key | Meaning |
| --- | --- |
| `kind` | The probe to use (see [Provider kinds](#provider-kinds)) |
| `base_url` | The server's root URL, without `/v1` |
| `name` | Display name, used when the tool creates the provider's block in a file |
| `api_key` | A literal key, `$NAME` or `${NAME}` from the environment, or `!command` whose output is the key |
| `sync` | `false` shows the provider in `status` and writes it to no consumer (default `true`) |
| `timeout` | Seconds to wait for each answer (default 5) |
| `exclude` | Glob patterns of model ids to leave out |
| `max_output` | Output limit for every model without one of its own |
| `context` | The window the server runs its models with. A model is written with the smaller of this and the context it reports, and its reported input limit is held to the same number. |
| `extra.<consumer kind>` | Keys merged into every model entry written for that kind of consumer |
| `reasoning_extra.<consumer kind>` | The same, for models that reason |
| `models."<id>"` | Corrections for one model |

A model table takes `name`, `context`, `max_input`, `max_output`, `vision`, `tools`,
`reasoning`, and `extra.<consumer kind>`. An output limit is chosen in this order: the
model's `max_output`, the provider's `max_output`, the reported value. A model's own
`context` is written as given, above the provider's `context` when it says so. A model with no
word on a flag is written as able to call tools, unable to see images, and without
reasoning.

A consumer takes `kind`, `path`, and optionally `providers`, a list of provider ids that
restricts what the consumer receives. Without it a consumer receives every provider whose
`sync` is true.

An unknown key anywhere in the index is an error that shows the key.

[`index.example.toml`](index.example.toml) is a commented index to copy and change. A test
loads it, so it stays true to the schema.

## Provider kinds

| Kind | Asks | Learns |
| --- | --- | --- |
| `litellm` | `/model/info` | Ids, input and output limits, vision, tools, reasoning, as the gateway's operator configured them |
| `ollama` | `/api/tags`, then `/api/show` for each model | Ids, context window, vision, tools, reasoning. Embedding models are dropped. |
| `openai` | `/v1/models` | Ids alone |

pi and opencode each carry a catalog of cloud models and refresh it themselves, so a
cloud provider needs no entry here. One with `sync = false` shows in `status` whether its
key works and what the key can reach.

## Consumer kinds

| Kind | File | How it is edited |
| --- | --- | --- |
| `opencode` | `opencode.jsonc` | Edited as text. The span of the provider's `models` value is replaced and nothing else, so comments outside that span survive and comments inside it do not. |
| `pi` | `models.json` | Loaded as JSON and written back with the provider's `models` list replaced. pi reads the file again each time `/model` opens. |

When a file has no block for a provider, the tool creates one from the index: the
endpoint at `base_url` plus `/v1`, and for pi the `api_key` setting as written (pi
resolves `$NAME` and `!command` itself). It writes no key into an opencode file, since
opencode keeps keys in its own store.

A provider whose entries already match is left untouched, so its hand formatting stays.

## Stale settings

A setting is stale when it names a model whose provider answered without it. A provider
that could not be reached makes no setting stale, since nothing is known about what it
serves.

On a terminal, `apply` lists the models live in that run across the providers the
consumer receives, and takes one of three answers for each stale setting:

| Answer | Effect |
| --- | --- |
| A number | The setting names that model instead |
| `r` | The setting is deleted, and the agent falls back to its own default |
| `l`, or Enter | The setting stays, and the warning returns at the next run |

A model with a table in the index draws the warning and no question. The table says you
expect the model back, as with one that is pulled and removed by turns. Delete the table
to be asked.

In an opencode file the edit replaces the setting's value or deletes its member, and
every comment outside that member survives. Removing `agents.<name>.model` leaves the
agent's block in place, empty when the model was all it held. pi keeps its default in
`settings.json` beside `models.json`. The tool rewrites that file with `defaultProvider`
and `defaultModel` changed or removed and every other key kept in order; the file's hand
formatting is lost.

## Backups

`apply` copies each file it is about to replace to
`~/.local/state/model-sync/backups/<consumer>/<timestamp>-<filename>`, mode 600, and
prints the path. The new file is written beside the old one and renamed over it, with the
old file's permissions. A symlinked file is written through the link. pi's `settings.json`
is backed up and written the same way when a stale default is replaced or removed.

## Adding a provider kind

Write one function in `src/model_sync/probes.py` under `@probe("<kind>")`. It receives
the provider's index entry and an HTTP client that already carries the base URL, the
timeout, and the bearer key, and it returns a list of `Model`, with `None` for anything
the server does not report. A probe raises an `httpx` error when the server could not be
asked, and the caller records the provider as unreachable.

## Adding a consumer kind

Subclass `Consumer` in a new module under `src/model_sync/consumers/`, decorate it with
`@consumer("<kind>")`, and import the module at the bottom of
`consumers/__init__.py`. The class supplies eight methods:

1. `load` reads the file.
2. `current` returns the entries a provider has in the file now.
3. `entry` renders one model in the file's vocabulary.
4. `stage` replaces a provider's list in memory.
5. `references` lists the settings that point at a model.
6. `repoint` makes one of those settings name another model.
7. `drop` deletes one of those settings.
8. `text` returns the file as it would be written.

Backups and the atomic write are inherited. A consumer whose settings live in a second
file, as pi's do, also overrides `pending` to name that file when it has been edited.

## Limits

- The context window reported for an Ollama model is the model's maximum. Ollama runs a
  model with the window set by `num_ctx` or by the server's default, which may be
  smaller. `ollama ps` shows the running window of a loaded model; set the provider's
  `context` to that number.
- A LiteLLM gateway reports whatever its operator typed. A gateway that repeats its input
  limit as its output limit needs `max_output` set in the index.
- A provider carries one id, used in the index and in every consumer's file. A consumer
  that calls the same provider by another id is unsupported.

## Development

`make` lists the targets. `make check` runs the linter and the tests; no test reaches a
real server or a real configuration file. `make install` puts `model-sync` on `PATH` as
an editable install, and the installed command runs the checkout.

Planned work and the rulings behind the tool live in `docs/dev/ledger/`, one ticket per
file. `make todo` lists what is pending.
