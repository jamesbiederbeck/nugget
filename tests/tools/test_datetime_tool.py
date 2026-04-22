import pytest
from nugget.tools.datetime_tool import execute


def test_default_utc():
    result = execute({})
    assert "datetime" in result
    assert result["timezone"] == "UTC"
    assert "T" in result["datetime"]


def test_explicit_utc():
    result = execute({"timezone": "UTC"})
    assert result["timezone"] == "UTC"
    assert "error" not in result


def test_named_timezone():
    result = execute({"timezone": "America/New_York"})
    assert result["timezone"] == "America/New_York"
    assert "error" not in result
    assert result["weekday"] in (
        "Monday", "Tuesday", "Wednesday", "Thursday",
        "Friday", "Saturday", "Sunday"
    )


def test_invalid_timezone():
    result = execute({"timezone": "Not/ATimezone"})
    assert "error" in result


def test_response_fields():
    result = execute({"timezone": "UTC"})
    for field in ("datetime", "date", "time", "timezone", "weekday"):
        assert field in result


def test_date_format():
    result = execute({"timezone": "UTC"})
    parts = result["date"].split("-")
    assert len(parts) == 3
    assert len(parts[0]) == 4  # year


def test_time_format():
    result = execute({"timezone": "UTC"})
    parts = result["time"].split(":")
    assert len(parts) == 3
