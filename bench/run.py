"""
Prompt compliance bench — measures whether the model uses output routing correctly.

Usage:
    python bench/run.py
    python bench/run.py --filter "file_*"
    python bench/run.py --repeat 3 --verbose
    python bench/run.py --run-name sweep_v1
    python bench/run.py --system-prompt bench/prompts/variant_01.j2   # phase 2
    python bench/run.py --db /tmp/other.db
    python bench/run.py --mock-tools          # no real tool execution, fastest
"""

import argparse
import csv
import fnmatch
import json
import re
import sys
import time
from itertools import groupby
from pathlib import Path

# Allow running from the project root without installing
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import db as bench_db
import ingest as bench_ingest

from nugget.backends.textgen import TextgenBackend
from nugget.config import Config
from nugget import tools as tool_registry
from nugget import approval as approval_mod

# ── Sink path approval: allow everything so bench never prompts ──────────────
_BENCH_APPROVAL = {
    "default": "allow",
    "sink_rules": [{"any": True, "action": "allow"}],
}

# Raised from on_tool_call to abort the backend loop immediately after the
# first tool call is captured. tool_calls_seen is already populated at raise time.
class _StopAfterFirstCall(Exception):
    pass


# ── TSV loading ──────────────────────────────────────────────────────────────

def load_cases(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


# ── Target resolution ────────────────────────────────────────────────────────

def _resolve_path(obj, path: str) -> str | None:
    """Resolve a dotted/indexed path into a nested dict/list structure.

    Supports simple keys ("key"), array indexing ("key[0]"), and chained
    access ("key.sub[1].field"). Returns json.dumps for non-scalars so
    constraint regexes can match against the serialised form.
    """
    for token in re.split(r'\.(?![^\[]*\])', path):
        if obj is None:
            return None
        m = re.match(r'^(\w+)\[(\d+)\]$', token)
        if m:
            obj = obj.get(m.group(1)) if isinstance(obj, dict) else None
            idx = int(m.group(2))
            obj = obj[idx] if isinstance(obj, list) and idx < len(obj) else None
        else:
            obj = obj.get(token) if isinstance(obj, dict) else None
    if obj is None:
        return None
    return json.dumps(obj) if isinstance(obj, (list, dict)) else str(obj)


def resolve_target(
    target: str,
    tool_calls: list[dict],
    text: str,
    thinking: str | None,
) -> str | None:
    if target == "response":
        return text or None
    if target == "reasoning":
        return thinking
    if target == "message":
        return text or None
    m = re.match(r'^tool_call\[(\d+)\]\.(.+)$', target)
    if m:
        n = int(m.group(1))
        path = m.group(2)
        if n >= len(tool_calls):
            return None
        call = tool_calls[n]
        if path == "name":
            return call["name"]
        if path.startswith("args."):
            return _resolve_path(call["args"], path[5:])
    return None


# ── Constraint evaluation ────────────────────────────────────────────────────

def evaluate_constraint(
    constraint_type: str,
    constraint_value: str | None,
    extracted: str | None,
) -> bool:
    if constraint_type == "absent":
        return extracted is None
    if constraint_type == "present":
        return extracted is not None
    if extracted is None:
        return False
    if constraint_type == "regex":
        return bool(re.search(constraint_value, extracted))
    if constraint_type == "min_length":
        return len(extracted) >= int(constraint_value)
    if constraint_type == "max_length":
        return len(extracted) <= int(constraint_value)
    return False


# ── System prompt rendering ──────────────────────────────────────────────────

def _render_system_prompt(
    system_prompt_override: Path | None,
    tool_schemas: list[dict],
    cfg: Config,
) -> str:
    if system_prompt_override is not None:
        raw = system_prompt_override.read_text()
        if system_prompt_override.suffix == ".j2":
            import jinja2
            from nugget.backends.textgen import format_tool_declaration
            tool_declarations = [format_tool_declaration(s) for s in tool_schemas]
            has_memory = any(
                s.get("function", {}).get("name") == "memory" for s in tool_schemas
            )
            return jinja2.Template(raw).render(
                system_prompt=cfg.system_prompt,
                tool_declarations=tool_declarations,
                thinking_effort=cfg.thinking_effort,
                has_memory=has_memory,
                has_tools=bool(tool_schemas),
            )
        return raw
    return cfg.system_prompt


# ── Group runner ─────────────────────────────────────────────────────────────

def run_group(
    group: list[dict],
    backend: TextgenBackend,
    cfg: Config,
    system_prompt: str,
    mock_tools: bool = False,
) -> dict:
    """
    Runs the model once for the group's shared prompt, then evaluates every
    constraint row in the group. All rows must share the same prompt and tools.

    With mock_tools=True the tool executor is stubbed and the backend loop is
    aborted immediately after the first tool call is captured — no real tool
    execution, no second completion round-trip.
    """
    first = group[0]
    tools_spec = first.get("tools", "*").strip()
    schemas = (
        tool_registry.schemas()
        if tools_spec == "*"
        else tool_registry.schemas(include=[t.strip() for t in tools_spec.split(",")])
    )

    tool_calls_seen: list[dict] = []

    def on_tool_call(name: str, args: dict) -> None:
        tool_calls_seen.append({"name": name, "args": dict(args)})
        if mock_tools:
            raise _StopAfterFirstCall

    has_tools = bool(schemas)
    stop_strings = ["<turn|>", "<|tool_response>"] if has_tools else ["<turn|>"]

    tool_executor = (
        (lambda n, a: {"status": "ok", "result": "mocked"})
        if mock_tools
        else (lambda n, a: tool_registry.execute(n, a))
    )

    t0 = time.perf_counter()
    try:
        text, thinking, _exchanges, finish_reason = backend.run(
            messages=[{"role": "user", "content": first["prompt"]}],
            tool_schemas=schemas,
            tool_executor=tool_executor,
            system_prompt=system_prompt,
            thinking_effort=cfg.thinking_effort,
            on_tool_call=on_tool_call,
            check_file_sink=approval_mod.check_file_sink,
            approval_config=_BENCH_APPROVAL,
        )
        error = None
    except _StopAfterFirstCall:
        text = ""
        thinking = None
        finish_reason = None
        error = None
    except Exception as exc:
        text = ""
        thinking = None
        finish_reason = "error"
        error = str(exc)
    latency_ms = int((time.perf_counter() - t0) * 1000)

    results = []
    for row in group:
        ct = row["constraint_type"]
        cv = row["constraint_value"] or None
        target = row["target"]
        extracted = resolve_target(target, tool_calls_seen, text, thinking)
        passed = evaluate_constraint(ct, cv, extracted)
        if not passed:
            if error:
                reason = f"error: {error}"
            else:
                reason = f"target={target!r} extracted={extracted!r} expected {ct}({cv!r})"
        else:
            reason = ""
        results.append({
            "id":               row["id"],
            "prompt_id":        row["prompt_id"],
            "passed":           passed,
            "extracted":        extracted,
            "reason":           reason,
            "constraint_type":  ct,
            "constraint_value": cv,
            "target":           target,
        })

    return {
        "prompt_id":    first["prompt_id"],
        "prompt":       first["prompt"],
        "text":         text,
        "thinking":     thinking,
        "tool_calls":   tool_calls_seen,
        "finish_reason": finish_reason,
        "stop_strings": stop_strings,
        "latency_ms":   latency_ms,
        "error":        error,
        "results":      results,
    }


# ── DB persistence ───────────────────────────────────────────────────────────

def _persist(
    conn,
    group_result: dict,
    case_name_to_id: dict[str, int],
    system_prompt_id: int,
    model_id: int,
    cfg: Config,
    run_id: int | None,
) -> None:
    user_prompt_id = bench_db.upsert_user_prompt(conn, group_result["prompt"])
    text_hash = bench_db.sha256(group_result["text"])
    tool_calls_json = (
        json.dumps(group_result["tool_calls"])
        if group_result["tool_calls"] else None
    )
    stop_strings_json = json.dumps(group_result["stop_strings"])

    response_id = bench_db.insert_response(
        conn,
        hash=text_hash,
        text=group_result["text"],
        thinking=group_result["thinking"],
        tool_calls_json=tool_calls_json,
        stop_strings_json=stop_strings_json,
        finish_reason=group_result["finish_reason"],
        temperature=cfg.temperature,
        prompt_tokens=None,
        completion_tokens=None,
        latency_ms=group_result["latency_ms"],
        model_id=model_id,
        system_prompt_id=system_prompt_id,
        user_prompt_id=user_prompt_id,
        run_id=run_id,
    )

    for result in group_result["results"]:
        tc_id = case_name_to_id.get(result["id"])
        if tc_id is None:
            continue
        bench_db.insert_test_result(
            conn,
            passed=int(result["passed"]),
            extracted_value=result["extracted"],
            system_prompt_id=system_prompt_id,
            user_prompt_id=user_prompt_id,
            response_id=response_id,
            test_case_id=tc_id,
            run_id=run_id,
        )


# ── Formatting ───────────────────────────────────────────────────────────────

GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
DIM    = "\033[2m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


def _fmt_result(r: dict) -> str:
    status = f"{GREEN}PASS{RESET}" if r["passed"] else f"{RED}FAIL{RESET}"
    id_col = f"{r['id']:<38}"
    ext = f"extracted={r['extracted']!r}"
    line = f"{status} [{id_col}]  {ext}"
    if not r["passed"]:
        line += f"  {DIM}({r['reason']}){RESET}"
    return line


def _fmt_repeat_result(case_id: str, passes: list[bool], extracted_values: list) -> str:
    n = len(passes)
    k = sum(passes)
    status = (
        f"{GREEN}PASS{RESET}" if k == n
        else (f"{RED}FAIL{RESET}" if k == 0 else f"{YELLOW}FLAK{RESET}")
    )
    unique = sorted(set(str(v) for v in extracted_values))
    id_col = f"{case_id:<38}"
    return f"{status} [{id_col}]  {k}/{n}  extracted={unique}"


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prompt compliance bench for output routing"
    )
    parser.add_argument("--cases", default="bench/cases/sinks.tsv",
                        help="Path to TSV cases file")
    parser.add_argument("--db", default="bench/bench.db", metavar="PATH",
                        help="SQLite database path (default: bench/bench.db)")
    parser.add_argument("--run-name", metavar="NAME",
                        help="Name for this run group (creates a run row; omit for ad-hoc)")
    parser.add_argument("--system-prompt", metavar="FILE",
                        help="Override system prompt (plain text or .j2 template)")
    parser.add_argument("--filter", metavar="GLOB",
                        help="Only run prompt groups whose prompt_id matches this glob")
    parser.add_argument("--repeat", type=int, default=1, metavar="N",
                        help="Run each prompt N times (measures stability)")
    parser.add_argument("--mock-tools", action="store_true",
                        help="Stub tool execution and stop after the first tool call "
                             "(no real I/O; captures model intent only)")
    parser.add_argument("--verbose", action="store_true",
                        help="Print model response text per group")
    args = parser.parse_args()

    cases_path = Path(args.cases)
    if not cases_path.exists():
        sys.exit(f"cases file not found: {cases_path}")

    # ── DB setup ─────────────────────────────────────────────────────────────
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = bench_db.open_db(db_path)

    # ── Ingest test cases ────────────────────────────────────────────────────
    prompt_to_cases = bench_ingest.ingest_cases(conn, cases_path)
    # Flatten to case_name → test_case_id for DB writes
    case_name_to_id: dict[str, int] = {
        name: tc_id
        for entries in prompt_to_cases.values()
        for name, tc_id in entries
    }

    # ── Load and filter cases ─────────────────────────────────────────────────
    all_rows = load_cases(cases_path)
    if args.filter:
        all_rows = [r for r in all_rows if fnmatch.fnmatch(r["prompt_id"], args.filter)]
    if not all_rows:
        sys.exit("no cases matched")

    # ── Backend setup ─────────────────────────────────────────────────────────
    cfg = Config.ensure_default()
    backend = TextgenBackend(cfg)

    system_prompt_override = Path(args.system_prompt) if args.system_prompt else None

    # Upsert stable per-run entities
    model_id = bench_db.upsert_model(conn, cfg.model)
    run_id = bench_db.insert_run(conn, args.run_name, None) if args.run_name else None

    total_cases = 0
    total_passed = 0

    # ── Group by prompt_id and iterate ───────────────────────────────────────
    sorted_rows = sorted(all_rows, key=lambda r: r["prompt_id"])
    for prompt_id, group_iter in groupby(sorted_rows, key=lambda r: r["prompt_id"]):
        group = list(group_iter)

        # Resolve schemas for system prompt rendering (use first row's tools spec)
        tools_spec = group[0].get("tools", "*").strip()
        schemas = (
            tool_registry.schemas()
            if tools_spec == "*"
            else tool_registry.schemas(include=[t.strip() for t in tools_spec.split(",")])
        )
        system_prompt = _render_system_prompt(system_prompt_override, schemas, cfg)
        system_prompt_id = bench_db.upsert_system_prompt(conn, system_prompt)

        if args.repeat == 1:
            gr = run_group(group, backend, cfg, system_prompt, mock_tools=args.mock_tools)
            _persist(conn, gr, case_name_to_id, system_prompt_id, model_id, cfg, run_id)
            for r in gr["results"]:
                total_cases += 1
                total_passed += int(r["passed"])
                print(_fmt_result(r))
            if args.verbose:
                print(f"  {DIM}response: {gr['text'][:120]!r}{RESET}")
        else:
            all_grs = [
                run_group(group, backend, cfg, system_prompt, mock_tools=args.mock_tools)
                for _ in range(args.repeat)
            ]
            for gr in all_grs:
                _persist(conn, gr, case_name_to_id, system_prompt_id, model_id, cfg, run_id)

            # Aggregate per test_case across repeats
            by_case: dict[str, list] = {}
            for gr in all_grs:
                for r in gr["results"]:
                    by_case.setdefault(r["id"], []).append(r)

            for case_id, case_results in by_case.items():
                passes = [r["passed"] for r in case_results]
                extracteds = [r["extracted"] for r in case_results]
                total_cases += 1
                total_passed += int(all(passes))
                print(_fmt_repeat_result(case_id, passes, extracteds))

            if args.verbose:
                for i, gr in enumerate(all_grs):
                    print(f"  {DIM}[{i+1}] {gr['text'][:80]!r}{RESET}")

    width = 50
    print("─" * width)
    pct = int(100 * total_passed / total_cases) if total_cases else 0
    color = GREEN if pct >= 80 else (RED if pct < 50 else YELLOW)
    print(f"{color}{BOLD}{total_passed}/{total_cases} passed ({pct}%){RESET}")


if __name__ == "__main__":
    main()
