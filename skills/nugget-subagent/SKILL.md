---
name: nugget-subagent
description: >
  Delegate a task to nugget — the user's locally-hosted LLM CLI — as a
  subagent instead of using Claude's own Agent tool. Use this skill whenever
  the user asks you to "run nugget", "use nugget to...", "send this to nugget",
  "spawn a nugget subagent", or when a task is better suited for the local
  model (privacy-sensitive work, tasks involving nugget's specific tools like
  wallabag, memory, wolfram, or local file browsing). Also use it when the
  user asks you to delegate something to the local model or when they
  explicitly want to avoid sending data to the cloud.
---

# Nugget Subagent

Nugget is a locally-hosted LLM CLI the user built at `~/code/ml/gemma`. You
run it in non-interactive mode as a subagent and return the result.

## Step 1 — Read the config and find profiles

```bash
jq '.profiles // {} | keys' ~/.config/nugget/config.json
```

Profiles you'll typically see:
- **chat** — no tools, conversational, fast
- **code** — thinking enabled, coding tasks
- **research** — grants http_fetch, grep_search, filebrowser, memory, jq, wolfram, wallabag
- **smart** — routes to a cloud model via OpenRouter (use when quality matters more than privacy)
- **strict** — asks approval before every tool call

## Step 2 — Choose a profile or tool subset

Match the task to a profile first. If no profile fits, build a minimal
`--include-tools` list from the tool names below.

**Available tools** (run `nugget --list-tools` if the list may have changed):
`calculator`, `filebrowser`, `get_datetime`, `grep_search`, `http_fetch`,
`jq`, `memory`, `notify`, `prompt`, `render_output`, `shell`, `spawn_agent`,
`tasks`, `wallabag`, `wolfram`

**Selection heuristic:**
- Pure reasoning / summarization / writing → no tools needed (omit `--include-tools`)
- Web research or reading saved articles → `--profile research`
- Code review or explanation → `--profile code`
- Simple chat or Q&A → `--profile chat`
- Needs cloud reasoning quality → `--profile smart`
- Task involves local files → include `filebrowser`, `grep_search`
- Math / unit conversion → include `calculator` or `wolfram`
- Persistent notes / memory → include `memory`

Do **not** include `shell` in the tool list unless the user explicitly asks —
it requires user approval anyway and will block the non-interactive run.
Do **not** include `prompt` — it blocks waiting for user input.

## Step 3 — Construct and run the command

```bash
nugget --non-interactive [--profile NAME | --include-tools t1,t2,...] "TASK"
```

Put the full task description as the positional `message` argument. Phrase it
as a clear, self-contained instruction — nugget gets no prior context.

**Examples:**

```bash
# Pure reasoning, no profile needed
nugget -n "Summarize the following in three bullet points: ..."

# Research task
nugget -n --profile research "Fetch https://example.com and summarize the main points"

# Local file work
nugget -n --include-tools filebrowser,grep_search "Search ~/notes for anything about 'oauth' and summarize what you find"

# Math
nugget -n --include-tools wolfram "Convert 42 kg to pounds and also tell me the gravitational acceleration on Mars"
```

## Step 4 — Return the output

The command prints the model's response to stdout. Capture it and relay it to
the user, clearly noting it came from nugget (the local model). If the command
exits non-zero or prints an error, report that too.

## Edge cases

- If `nugget` is not on PATH, it's at `~/.local/bin/nugget` or installable via
  `cd ~/code/ml/gemma && uv tool install ".[web]" --force`.
- The local model (`gemma-4-E4B-it-uncensored`) has a 2048-token output cap
  by default. For long outputs, add `--max-tokens 4096`.
- If the task needs more than 4 tool-call iterations, add `--max-tokens` and
  consider whether a profile's `max_turns` config is sufficient (default: 16).
- `--thinking` or `--thinking-effort 2` can help for complex reasoning if the
  default profile doesn't have thinking enabled.
