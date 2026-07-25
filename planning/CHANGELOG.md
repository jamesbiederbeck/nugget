# Changelog

## [0.8.1]

### Fixed
- `claude_history`: pin the wrapped subprocess's cwd to nugget's own process directory rather than inheriting an arbitrary caller cwd.

### Docs
- Improved tool description for `claude_history`.

## [0.8.0]

### Added
- **MCP client (roadmap #6):** `mcp_servers` config key loads tools from external MCP servers (stdio or Streamable HTTP) into nugget's own tool-calling loop, namespaced `mcp__<server>__<tool>`. Rides the existing approval pipeline (`"ask"` by default for unvetted external tools). Never re-exposed through nugget's own MCP server.
- **MCP server (roadmap #6):** `nugget-server` can expose the active profile's native tools to external MCP clients (Claude Code, Claude Desktop, etc.) over Streamable HTTP when `mcp_server.enabled` is set, mounted at `mcp_server.path` (default `/mcp`). Only tools whose approval statically resolves to `"allow"` are listed or callable — no interactive approval-prompt channel for MCP calls yet (tracked as `NUG-023`).

## [0.7.0]

### Added
- **`claude_history` tool:** wraps the third-party `claude-history` agent protocol, exposing it to the model as a built-in tool.
- **`nugget-subagent` skill:** installable via `npx skills add jamesbiederbeck/nugget --skill nugget-subagent`, letting Claude Code delegate tasks to a local nugget subagent.
- Slash command completions now auto-show while typing, instead of requiring an explicit trigger.

### Fixed
- Prior-turn thinking blocks (`<|channel>thought>`) are stripped from the agentic prompt context — both session history and the current tool-calling loop — preventing repetition loops in multi-step tool-calling sequences.

## [0.6.1]

### Added
- **stdin support:** `nugget` now reads from stdin when it is not a TTY. Piped or redirected input is appended to the positional message (if any) and the process exits after the response — no `-n` needed. e.g. `gh pr diff 42 | nugget "summarize:"` or `nugget "review:" < file.txt`.
- **Local OpenAI-compatible backends via `--api-url`:** `OpenRouterBackend` now resolves the target URL from `api_url` → `openrouter_base_url` → `https://openrouter.ai/api`. When the URL is local (`localhost` / `127.*`), the API key requirement and OpenRouter-specific headers (`HTTP-Referer`, `X-Title`) are skipped, enabling use with LM Studio, Ollama, or any local proxy.

---

## [0.6.0]

### Added
- **`/profile` command:** switch named config profiles at runtime without restarting. Profiles are defined under `profiles` in `config.json`; `/profile <name>` merges the profile's keys into the active config for the rest of the session.
- **`prompt_toolkit` REPL:** interactive prompt with slash-command completion, history persistence, and a `prompt` tool for mid-conversation user input.
- **`--api-url` flag / `NUGGET_API_URL` env var:** override the backend URL from the CLI without editing config.

---

## [0.5.0]

### Added
- **Interactive tool approvals in web UI (roadmap #7):** `"ask"`-gated tools now pause the request and emit an `approval_required` SSE event. The frontend injects Allow/Deny buttons into the tool-call block; the user's response is sent via `POST /api/approvals/{call_id}/respond`, which unblocks the tool executor. `GET /api/approvals/pending` lists outstanding approvals.
- **`render_output` display formatting:** New optional `format` arg (`"markdown"` | `"text"`, default `"markdown"`). When `output` is omitted the tool wraps its result in a `{_display_format, _content}` envelope; the CLI renders it with `print_routed_output()`, and the web UI renders markdown via marked.js for display sinks.
- **`render_output`-nested web approvals (roadmap #20):** `ask`-gated inner tools called through `render_output` now route through the same web approval flow instead of being silently denied.
- `on_tool_routed` callback wired through server SSE (`tool_routed` event type).
- marked.js (v14, CDN) added to web UI for markdown rendering.

### Fixed
- `__main__.py`: `finally` block for subagent context-var reset was placed before `except` clauses, preventing `BackendError` and generic exceptions from reaching their handlers. Reordered so `except` precedes `finally`.

---

## [0.4.2]

### Added
- Server request/response logging at INFO level: `nugget.server` logger emits one line on receipt of a chat request (session, backend, model, input chars) and one line on completion (elapsed time, tool call count, finish reason, and prompt/completion/total token counts when available). OpenRouter streaming now requests `stream_options: {include_usage: true}` to capture token counts; textgen non-streaming captures usage from the API response.
- `Backend` ABC gains a `last_usage: dict | None` class attribute; backends populate it after each API call with token-count stats from the upstream response.

---

## [0.4.1]

### Added
- `wolfram` tool — Wolfram|Alpha LLM API wrapper
- `grep_search` tool (ripgrep wrapper, allow-by-default)
- `http_fetch` tool (GET/HEAD allow, mutating methods ask)
- `jq` tool (JMESPath query over JSON / `$var` payloads)
- `tasks` tool (SQLite task list, delete asks)
- `filebrowser` write/edit/filesystem operations with approval gate
- `wallabag`: support posting raw content without a real URL
- Tool registry `reload()` and server `/api/tools/reload` hot-reload endpoint
- `--model` flag to CLI; `--backend` and `--model` flags to server

### Fixed
- OpenRouter: validate API key on init, sort tool calls by stream index
- `spawn_agent`: `return_thinking=true` now actually returns the child's thinking block. Previously the arg was accepted and documented but `backend.run()` was called with `thinking_effort=0`, so the child never generated thinking and the result always omitted the field. Fix: when `return_thinking=true`, the child runs with `thinking_effort=max(1, parent_config.thinking_effort)`. The `thinking` key is now always present in the result when requested (null if the child produced none). Motivated by sessions b3077b8b and d0b46965 where the model hallucinated this arg, suggesting it was a reasonable expectation that the feature should actually honour.

### Docs
- `tool_docs/CONFIG.md` — practical config reference with JSON schema (moved from `TOOL_SPEC.md`)
- Updated CLAUDE.md: backend return type, request flow, config pointer, new flags

---

## [0.3.0]

### Added
- `Backend` ABC with typed signatures (NUG-002)
- OpenRouter backend targeting `/v1/chat/completions` (NUG-003)
- `render_output` dispatch — routes tool output through `display`, `file:`, and `$var` sinks (NUG-001); `_routing.py` helpers extracted

---

## [0.2.1]

### Added
- `develop → staging → main` branching strategy with per-branch CI and Docker builds

---

## [0.2.0]

### Added
- Release pipeline — CI workflow, PR template, `--version` flag
- `render_output` stub with bench cases
- Benchmark `--mock-tools` flag for fast tool-call intent testing

### Fixed
- `Backend.run()` signature corrected in docs (`35742d9`)

---

## [pre-0.2.0]

### Added
- Full benchmarking suite (SQLite result storage, Docker deployment, hardened output routing)
- Streaming output, slash commands
- Web server (`nugget-server`) with SSE streaming and CI workflow
- `wallabag` save-article tool
- `gotify` push notification tool
- `memory` tool: store/recall/search/list/delete with pin support
- Memory link resolution with configurable depth and cross-linking
- `src/` layout restructure; `textgen` backend consolidated; backends abstraction + test suite
- Dockerfile and project metadata

### Fixed
- Rendering issue for model messages
- `readline`: wrap ANSI color codes in prompt with non-printing delimiters (`\001`/`\002`)
- Build system (`pyproject.toml`)
- Templates included in installed package
