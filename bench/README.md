# Bench

A prompt-compliance bench that measures whether a model, given nugget's
tool schemas and system prompt, actually calls tools the way the prompt
asks it to — output routing (`display` vs `file:` vs stdout sinks),
`spawn_agent` argument shape, and shell-passthrough framing among them.

Every case is a (prompt, expected-shape) pair. The bench sends the prompt
through a real backend, parses the response into `(text, thinking,
tool_calls, finish_reason)`, extracts a value at a declared path (e.g.
`tool_call[0].args.output`), and checks it against a constraint (`regex`,
`present`, `absent`, `min_length`, `max_length`). Every case, response,
and pass/fail result is persisted to a SQLite database
(`bench/bench.db`) so you can track stability and regressions across
prompt-template edits, not just get a one-off pass rate.

See [erd.md](erd.md) for the full schema.

## Layout

| Path | Purpose |
|---|---|
| `run.py` | CLI runner — loads a TSV, runs each prompt through a backend, scores it, persists results |
| `ingest.py` | Idempotently upserts prompts/test cases from a TSV into the DB (used by `run.py`, also usable standalone) |
| `db.py` | Thin SQLite wrapper — schema init, upserts, inserts |
| `schema.sql` | The DB schema (SQLite, WAL mode, FKs on) |
| `erd.md` | Entity-relationship diagram and full column reference |
| `cases/*.tsv` | Test case definitions, one file per feature area (see below) |
| `fixtures/` | Supporting fixture data referenced by cases |
| `bench.db` | The SQLite results database (gitignored — regenerate locally) |

## Running it

```bash
python bench/run.py                                    # default: cases/sinks.tsv
python bench/run.py --cases bench/cases/subagent.tsv
python bench/run.py --filter "file_*"                   # only prompt_ids matching a glob
python bench/run.py --repeat 3                           # measure stability across repeats
python bench/run.py --run-name sweep_v1                  # tag results with a named run
python bench/run.py --system-prompt bench/prompts/variant_01.j2   # try a prompt variant
python bench/run.py --mock-tools                          # stub tool execution, capture intent only
python bench/run.py --db /tmp/other.db                    # write to a scratch DB instead of bench/bench.db
```

Each TSV row belongs to a `prompt_id` group; rows in the same group share
a prompt and are evaluated together against that one response. Query
`bench.db` directly (or write a script against `db.py`) to compare pass
rates across runs, models, or prompt-template revisions.

### Asserting that an optional arg was *not* set

`absent` passes only when the target path resolves to nothing, and
`regex` fails outright on a missing value — so neither constraint can
express "omitted **or** explicitly false". Cases that assert a model
left an optional boolean alone (`memory_pin.tsv`'s `nopin_*.pin` rows,
`sinks.tsv`'s `no_sink_*.output` rows) use `absent`, which is the shape
the prompt actually asks for. A model that passes an explicit
`pin=false` or `output=null` is arguably also correct but will score as
a failure. If that starts showing up in results, read it as a signal
about the model's arg-emission habits rather than a real regression.

## Not just Gemma

Nothing about the case format or the schema is Gemma-specific. A case is
just a prompt plus a target/constraint pair evaluated against the parsed
*shape* of a response — which tool was called, what args it got, whether
reasoning text is present — never against raw special tokens. The `model`
table exists precisely so results from different models sit side by side
in the same database, indexed by `response.model_id`.

`run.py` currently wires up `TextgenBackend` directly (nugget's default,
Gemma-4-flavored backend), so out of the box it benches whatever model
your text-generation-webui instance is serving. To bench a different
model:

- **Same tool-calling shape, different backend** — swap in any class
  implementing the `Backend` ABC (e.g. `OpenRouterBackend`) in `run.py`.
  Everything downstream (scoring, persistence, the DB schema) is
  unchanged.
- **A model nugget doesn't talk to at all** — generate responses with
  your own harness, then call `db.py`/`ingest.py` directly to record them
  in the same shape (`tool_calls` as `{name, args}` JSON, etc.). You get
  directly comparable pass rates against every other model in
  `bench.db` without changing a single test case.

## Docs

- [erd.md](erd.md) — schema, target-path syntax, constraint types, test
  case versioning rules, and column-by-column notes.
