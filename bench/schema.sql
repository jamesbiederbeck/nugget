-- Prompt compliance bench database schema
-- SQLite
--
-- Per-connection setup required in application code (not enforced by this file):
--   PRAGMA journal_mode = WAL;
--   PRAGMA foreign_keys = ON;

-- ── Schema versioning ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR IGNORE INTO meta VALUES ('schema_version', '1');

-- ── Content tables ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS system_prompt (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    hash       TEXT    NOT NULL UNIQUE,   -- SHA-256 of text
    text       TEXT    NOT NULL,
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS user_prompt (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    hash       TEXT    NOT NULL UNIQUE,   -- SHA-256 of text
    text       TEXT    NOT NULL,
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ── Model registry ────────────────────────────────────────────────────────────
-- Normalised lookup prevents "gemma-3-4b" vs "gemma3:4b" drift across sweeps.
-- name is case-insensitive unique: insert canonical lowercase identifiers.

CREATE TABLE IF NOT EXISTS model (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL UNIQUE COLLATE NOCASE,   -- canonical model identifier
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ── Run grouping ──────────────────────────────────────────────────────────────
-- NULL run_id on response/test_result = ad-hoc single invocation.

CREATE TABLE IF NOT EXISTS run (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT,
    notes      TEXT,
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_run_created ON run(created_at);

-- ── Response ──────────────────────────────────────────────────────────────────
-- One row per model completion. thinking is null when disabled or absent.
-- hash is NOT UNIQUE: repeated invocations at low temperature can produce
-- identical text and must each have their own row for stability tracking.
-- stop_strings and tool_calls are JSON arrays.
-- temperature / prompt_tokens / completion_tokens / latency_ms may be NULL
-- when not reported by the backend.

CREATE TABLE IF NOT EXISTS response (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    hash              TEXT    NOT NULL,   -- SHA-256 of text; plain index, not UNIQUE
    text              TEXT    NOT NULL,   -- parsed final response text
    thinking          TEXT,               -- parsed thinking block, if any
    tool_calls        TEXT    CHECK (tool_calls   IS NULL OR json_valid(tool_calls)),    -- JSON [{name, args}, ...]
    stop_strings      TEXT    CHECK (stop_strings IS NULL OR json_valid(stop_strings)),  -- JSON array
    finish_reason     TEXT    CHECK (finish_reason IS NULL
                                     OR finish_reason IN ('stop', 'length', 'tool_calls', 'error')),
    temperature       REAL,               -- sampling temperature, if recorded
    prompt_tokens     INTEGER,            -- tokens in the prompt, if reported
    completion_tokens INTEGER,            -- tokens in the completion, if reported
    latency_ms        INTEGER,            -- wall-clock ms from request to last token
    model_id          INTEGER NOT NULL REFERENCES model(id)         ON DELETE RESTRICT,
    system_prompt_id  INTEGER NOT NULL REFERENCES system_prompt(id) ON DELETE RESTRICT,
    user_prompt_id    INTEGER NOT NULL REFERENCES user_prompt(id)   ON DELETE RESTRICT,
    run_id            INTEGER             REFERENCES run(id)         ON DELETE RESTRICT,  -- NULL = ad-hoc
    created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_response_hash          ON response(hash);
CREATE INDEX IF NOT EXISTS idx_response_model         ON response(model_id);
CREATE INDEX IF NOT EXISTS idx_response_system_prompt ON response(system_prompt_id);
CREATE INDEX IF NOT EXISTS idx_response_user_prompt   ON response(user_prompt_id);
CREATE INDEX IF NOT EXISTS idx_response_run           ON response(run_id);
CREATE INDEX IF NOT EXISTS idx_response_created       ON response(created_at);
-- Covering index for stability queries: count distinct outputs per (system_prompt, user_prompt, model)
CREATE INDEX IF NOT EXISTS idx_response_dedup
    ON response(system_prompt_id, user_prompt_id, model_id, hash);

-- ── Test case ─────────────────────────────────────────────────────────────────
-- Model-agnostic. constraint_type governs how constraint_value is evaluated:
--
--   absent      extracted_value must be NULL          (constraint_value must be NULL)
--   present     extracted_value must be non-NULL      (constraint_value must be NULL)
--   min_length  len(extracted_value) >= constraint_value cast as int
--   max_length  len(extracted_value) <= constraint_value cast as int
--   regex       re.search(constraint_value, extracted_value) is truthy
--
-- Note: regex validity and numeric validity of constraint_value for length types
-- cannot be enforced at the DB layer — the writer is responsible.
--
-- VERSIONING: name is UNIQUE. Changing constraint_type, constraint_value, or
-- target requires a new row (new name). constraint_hash is for drift detection
-- only — if a hash in test_result.test_case_id no longer matches the live row,
-- the case was edited in place, which breaks historical comparisons.
-- constraint_hash = SHA-256(constraint_type || ':' || COALESCE(constraint_value,'') || ':' || target)
--
-- target is a dot-path expression resolved against the parsed response:
--
--   tool_call[N].output           output routing arg of the Nth tool call
--   tool_call[N].name             tool name of the Nth tool call
--   tool_call[N].args.<key>       arbitrary arg of the Nth tool call
--   reasoning                     thinking block text
--   response                      parsed final response text
--   message                       full raw completion (thinking + tool tokens + text)

CREATE TABLE IF NOT EXISTS test_case (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT    NOT NULL UNIQUE,
    constraint_type  TEXT    NOT NULL CHECK (constraint_type IN ('absent', 'present', 'min_length', 'max_length', 'regex')),
    constraint_value TEXT    CHECK (
        (constraint_type IN ('absent', 'present') AND constraint_value IS NULL)
        OR
        (constraint_type NOT IN ('absent', 'present') AND constraint_value IS NOT NULL)
    ),
    constraint_hash  TEXT    NOT NULL,   -- SHA-256(constraint_type || ':' || COALESCE(constraint_value,'') || ':' || target); writer-trusted
    target           TEXT    NOT NULL,   -- extraction path (see above)
    notes            TEXT
);

-- ── Test result ───────────────────────────────────────────────────────────────
-- One row per (response × test_case) evaluation; enforced by uq_test_result_eval.
-- system_prompt_id, user_prompt_id, and run_id are denormalised from response for
-- cheap sweep aggregations (e.g. pass rate per system_prompt variant).
-- A trigger enforces they always match the parent response row.
-- extracted_value is the string the constraint was applied to.

CREATE TABLE IF NOT EXISTS test_result (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    passed           INTEGER NOT NULL CHECK (passed IN (0, 1)),
    extracted_value  TEXT,                       -- what the constraint ran against
    system_prompt_id INTEGER NOT NULL REFERENCES system_prompt(id) ON DELETE RESTRICT,
    user_prompt_id   INTEGER NOT NULL REFERENCES user_prompt(id)   ON DELETE RESTRICT,
    response_id      INTEGER NOT NULL REFERENCES response(id)      ON DELETE CASCADE,
    test_case_id     INTEGER NOT NULL REFERENCES test_case(id)     ON DELETE RESTRICT,
    run_id           INTEGER             REFERENCES run(id)         ON DELETE RESTRICT,  -- NULL = ad-hoc
    created_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_test_result_eval            ON test_result(response_id, test_case_id);
CREATE INDEX IF NOT EXISTS idx_test_result_response              ON test_result(response_id);
CREATE INDEX IF NOT EXISTS idx_test_result_test_case             ON test_result(test_case_id);
CREATE INDEX IF NOT EXISTS idx_test_result_system_prompt         ON test_result(system_prompt_id);
CREATE INDEX IF NOT EXISTS idx_test_result_user_prompt           ON test_result(user_prompt_id);
CREATE INDEX IF NOT EXISTS idx_test_result_run                   ON test_result(run_id);
CREATE INDEX IF NOT EXISTS idx_test_result_created               ON test_result(created_at);
-- Covering index for pass-rate sweep queries: group by (run, system_prompt, test_case), count passes
CREATE INDEX IF NOT EXISTS idx_test_result_sweep
    ON test_result(run_id, system_prompt_id, test_case_id, passed);
-- Partial index for failure drill-down queries
CREATE INDEX IF NOT EXISTS idx_test_result_failures
    ON test_result(run_id, test_case_id)
    WHERE passed = 0;

-- ── Denorm integrity trigger ──────────────────────────────────────────────────
-- Ensures test_result.{system_prompt_id, user_prompt_id, run_id} always match
-- the parent response row. Always update all three denorm columns in one
-- statement — an intermediate UPDATE that changes only one will trigger this.

CREATE TRIGGER IF NOT EXISTS trg_test_result_denorm_insert
BEFORE INSERT ON test_result
BEGIN
    SELECT RAISE(ABORT, 'test_result denormalised columns do not match parent response')
    WHERE EXISTS (
        SELECT 1 FROM response
        WHERE id = NEW.response_id
          AND (
              system_prompt_id != NEW.system_prompt_id
              OR user_prompt_id != NEW.user_prompt_id
              OR run_id IS NOT NEW.run_id
          )
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_test_result_denorm_update
BEFORE UPDATE ON test_result
BEGIN
    SELECT RAISE(ABORT, 'test_result denormalised columns do not match parent response')
    WHERE EXISTS (
        SELECT 1 FROM response
        WHERE id = NEW.response_id
          AND (
              system_prompt_id != NEW.system_prompt_id
              OR user_prompt_id != NEW.user_prompt_id
              OR run_id IS NOT NEW.run_id
          )
    );
END;
