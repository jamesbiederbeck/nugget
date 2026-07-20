import base64
import struct
import subprocess

import pytest

from nugget.tools.pdf import execute


def _make_pdf(text: str) -> bytes:
    """Hand-build a minimal valid single-page PDF with an optional text run."""
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 5 0 R >> >> "
        b"/MediaBox [0 0 600 200] /Contents 4 0 R >>\nendobj\n",
    ]
    stream = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode()
    objects.append(b"4 0 obj\n<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream\nendobj\n")
    objects.append(b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for obj in objects:
        offsets.append(len(out))
        out += obj
    xref_start = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (len(objects) + 1, xref_start)
    return bytes(out)


def _skip_if_missing(binary):
    import shutil
    if shutil.which(binary) is None:
        pytest.skip(f"{binary} not installed")


def test_path_required():
    assert "error" in execute({})


def test_missing_file(tmp_path):
    result = execute({"path": str(tmp_path / "nope.pdf")})
    assert "error" in result


def test_not_a_pdf(tmp_path):
    f = tmp_path / "notes.txt"
    f.write_text("hello")
    result = execute({"path": str(f)})
    assert "error" in result
    assert "not a pdf" in result["error"].lower()


def test_extractable_text_path(tmp_path):
    _skip_if_missing("pdftotext")
    f = tmp_path / "doc.pdf"
    f.write_bytes(_make_pdf("Hello nugget test document with enough characters to pass the minimum length check"))
    result = execute({"path": str(f)})
    assert result["_attachment"] is True
    assert result["images"] == []
    assert "Hello nugget test document" in result["text"]


def test_rasterization_fallback_for_sparse_text(tmp_path):
    _skip_if_missing("pdftotext")
    _skip_if_missing("pdftoppm")
    f = tmp_path / "scanned.pdf"
    f.write_bytes(_make_pdf(""))  # essentially no text layer
    result = execute({"path": str(f)})
    assert result["_attachment"] is True
    assert len(result["images"]) == 1
    img = result["images"][0]
    assert img["mime"] == "image/png"
    assert img["source"] == "scanned.pdf#page=1"
    assert base64.b64decode(img["data_b64"]).startswith(b"\x89PNG")


def test_max_pages_validation(tmp_path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(_make_pdf("text"))
    result = execute({"path": str(f), "max_pages": 0})
    assert "error" in result


def test_pdftotext_not_found(tmp_path, monkeypatch):
    f = tmp_path / "doc.pdf"
    f.write_bytes(_make_pdf(""))

    def fake_run(cmd, **kwargs):
        if cmd[0] == "pdftotext":
            raise FileNotFoundError("pdftotext not found")
        raise FileNotFoundError("pdftoppm not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = execute({"path": str(f)})
    assert "error" in result
    assert "pdftoppm" in result["error"]
