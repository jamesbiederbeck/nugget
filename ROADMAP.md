# Nugget — Roadmap

## Done
- [x] Basic chat interface
- [x] Tool calling framework
- [x] Thinking (chain-of-thought)
- [x] Session management (save, resume by ID, resume last)
- [x] Swappable backends
- [x] Pinned memories in system prompt
- [x] Output routing — `display`, `file:`, `$var` sinks
- [x] Prompt compliance bench with SQLite result storage

## Output routing

### Jinja template sink
Add a `template` output sink. The model binds tool outputs to named variables
(`output: "$article"`) then writes its final response as a Jinja2 template
(`The title is {{ article.title }}`). The harness renders it before displaying
or saving — the model never needs large tool payloads inlined into context.

Implementation sketch:
- New sink value: `output: "template"` (or `output: "render"`)
- When the turn ends with bound variables and `finish_reason="stop"`, render
  `final_text` as a Jinja2 template with the bindings as context
- Bench test: `constraint_type=regex`, `constraint_value=^template$`,
  `target=tool_call[0].args.output`

## Memory & retrieval
- [ ] Semantic search over past sessions and memory (vector index on SQLite)

## Bench
- [ ] System-prompt variant sweeping — run the full case matrix against multiple
  `.j2` prompt variants and compare pass rates in the DB
- [ ] `--repeat` flakiness report — query DB for cases with mixed pass/fail
  across repeats and surface them as a stability table
