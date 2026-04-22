import pytest
from nugget.tools.calculator import execute


@pytest.mark.parametrize("expr,expected", [
    ("2 + 2", 4),
    ("10 - 3", 7),
    ("3 * 4", 12),
    ("10 / 4", 2.5),
    ("10 // 3", 3),
    ("10 % 3", 1),
    ("2 ** 8", 256),
    ("-5", -5),
    ("+3", 3),
    ("(2 + 3) * 4", 20),
    ("2 + 3 * 4", 14),
    ("100 / (2 + 3)", 20.0),
])
def test_basic_expressions(expr, expected):
    result = execute({"expression": expr})
    assert "error" not in result
    assert result["result"] == expected
    assert result["expression"] == expr


def test_nested_expression():
    result = execute({"expression": "((2 + 3) * (4 - 1)) ** 2"})
    assert result["result"] == 225


def test_invalid_expression_syntax():
    result = execute({"expression": "2 +"})
    assert "error" in result


def test_invalid_expression_string():
    result = execute({"expression": "'hello'"})
    assert "error" in result


def test_invalid_expression_builtin():
    result = execute({"expression": "print('hi')"})
    assert "error" in result


def test_empty_expression():
    result = execute({"expression": ""})
    assert "error" in result


def test_missing_expression_key():
    result = execute({})
    assert "error" in result


def test_division_by_zero():
    result = execute({"expression": "1 / 0"})
    assert "error" in result
