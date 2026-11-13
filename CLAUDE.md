# CLAUDE.md

@README.md

## Working here

- **Never run `model-sync apply` against the real index unasked.** It is the one command
  that writes files outside this checkout. `make status` and `make diff` are read-only
  and safe to run. Tests use a temporary index and never reach a real server.
- **Never print an API key.** `~/.config/model-sync/index.toml` and pi's `models.json` can
  hold keys or the commands that fetch them. Redact `api_key` and `apiKey` values before
  showing either file.
- **Planned work and rulings live in `docs/dev/ledger/`**, one ticket per file, run through
  the `roadmap` command (`make todo` lists the queue). Log a finding as a ticket and keep
  going. Cite a ticket by its full label, such as `TODO-001-apply-asks`.
- **`index.example.toml` is loaded by a test.** A change to the index schema changes that
  file and the README's key tables in the same commit.
