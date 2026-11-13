# The model-sync command: its checks, and putting it on PATH. Everything here takes seconds.
# Plain `make` lists the targets.

ifneq ($(firstword $(sort $(MAKE_VERSION) 4.3)),4.3)
$(error GNU Make 4.3+ required, found $(MAKE_VERSION). On macOS: brew install make, then run gmake, or put "$$(brew --prefix)/opt/make/libexec/gnubin" first on PATH)
endif

.DEFAULT_GOAL := help
.DELETE_ON_ERROR:
MAKEFLAGS += --no-print-directory

# --- Working on it

.PHONY: help
help:  ## List these targets (what plain `make` does)
	@awk 'function wrap(s, at, room,   n, i, word, line, out) { \
	         n = split(s, word, " "); line = ""; out = ""; \
	         for (i = 1; i <= n; i++) \
	             if (line != "" && length(line) + 1 + length(word[i]) > room) { \
	                 out = out line "\n" sprintf("%" at "s", ""); line = word[i] \
	             } else line = (line == "" ? word[i] : line " " word[i]); \
	         return out line \
	     } \
	     BEGIN { FS = ":.*## "; width = 80 } \
	     /^# --- / { sub(/^# --- /, ""); pending = $$0; next } \
	     /^[a-zA-Z][a-zA-Z0-9_-]*:.*## / { \
	         if (pending != "") { n++; kind[n] = "s"; text[n] = pending; pending = "" } \
	         n++; kind[n] = "t"; name[n] = $$1; text[n] = $$2; \
	         if (length($$1) > w) w = length($$1) \
	     } \
	     END { \
	         for (i = 1; i <= n; i++) \
	             if (kind[i] == "s") printf "\n%s\n", text[i]; \
	             else printf "  %-*s  %s\n", w, name[i], wrap(text[i], w + 4, width - w - 4); \
	         print "" \
	     }' $(MAKEFILE_LIST)

.PHONY: check
check: lint test  ## Lint and the tests, which include the ledger's own check

.PHONY: test
test:  ## The test suite
	uv run pytest

.PHONY: lint
lint:  ## Static checks, writing nothing
	uv run ruff check .
	uv run ruff format --check .

.PHONY: format
format:  ## Reformat and autofix in place
	uv run ruff format .
	uv run ruff check --fix .

.PHONY: install
install:  ## Put `model-sync` on PATH from this checkout
	uv tool install --editable .

.PHONY: uninstall
uninstall:  ## Remove the installed `model-sync`
	uv tool uninstall model-sync

# --- The ledger

.PHONY: todo
todo:  ## What is pending in the ledger, and for how long
	@uv run roadmap status

.PHONY: todo-details
todo-details:  ## The same, with each ticket's opening paragraph, through your pager
	@uv run roadmap status --details

# --- Running it against the real index

# Read-only: both ask the providers and neither writes a consumer's file. `apply` has no
# target on purpose, since it is the one command that changes files outside this checkout.
.PHONY: status
status:  ## Ask every provider in the index what it serves
	@uv run model-sync status

.PHONY: diff
diff:  ## Show what `model-sync apply` would change, writing nothing
	@uv run model-sync diff
