"""
Deterministic large grep payload for subagent bench and e2e tests.

Used so distillation cases don't depend on the real grep_search tool
or any specific file on disk.
"""

_FILES = [
    ("src/nugget/backends/textgen.py", [12, 45, 78, 112, 156, 189, 234, 267]),
    ("src/nugget/tools/memory.py",     [8, 23, 51, 74, 99, 118, 142, 167, 188, 201]),
    ("src/nugget/session.py",          [15, 34, 67]),
    ("src/nugget/config.py",           [22, 48]),
    ("src/nugget/__main__.py",         [31, 55, 88, 103, 144, 177, 212]),
    ("src/nugget/server.py",           [19, 43, 71, 96, 127]),
    ("src/nugget/approval.py",         [9, 28]),
    ("tests/test_session.py",          [14, 38, 62, 85]),
    ("tests/backends/test_textgen.py", [11, 35, 59, 83, 107]),
    ("bench/run.py",                   [17, 41]),
]

MOCK_GREP_PATTERN = "TODO"


def make_matches() -> list[str]:
    """Return a deterministic list of grep match lines (file:line:text format)."""
    matches = []
    for filepath, lines in _FILES:
        for lineno in lines:
            matches.append(f"{filepath}:{lineno}: # TODO: fix this")
    return matches


def make_payload() -> dict:
    """Return a mock grep_search result dict (mirrors real tool output shape)."""
    matches = make_matches()
    return {
        "pattern": MOCK_GREP_PATTERN,
        "path": ".",
        "matches": matches,
        "count": len(matches),
        "truncated": False,
    }


def expected_top_file() -> str:
    """The file with the most matches — used to assert subagent correctness."""
    counts: dict[str, int] = {}
    for filepath, lines in _FILES:
        counts[filepath] = len(lines)
    return max(counts, key=lambda k: counts[k])
