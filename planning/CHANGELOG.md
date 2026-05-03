# Changelog

## [0.4.0] — in progress

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
