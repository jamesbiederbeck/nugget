import base64
import subprocess
import tempfile
from pathlib import Path

APPROVAL = "allow"

SCHEMA = {
    "type": "function",
    "function": {
        "name": "pdf",
        "description": (
            "Read a PDF file. Returns extracted text if the PDF has a text layer; "
            "otherwise rasterizes pages to images and returns them as attachments "
            "for visual reading (requires a vision-capable model)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the PDF file.",
                },
                "max_pages": {
                    "type": "integer",
                    "description": (
                        "Max pages to rasterize if the PDF has no usable text layer "
                        "(default 10)."
                    ),
                },
            },
            "required": ["path"],
        },
    },
}

_MIN_TEXT_LENGTH = 50


def _extract_text(target: Path) -> str | None:
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", str(target), "-"],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _rasterize(target: Path, max_pages: int) -> tuple[list[dict], str | None]:
    with tempfile.TemporaryDirectory() as tmp:
        prefix = f"{tmp}/page"
        try:
            result = subprocess.run(
                ["pdftoppm", "-png", "-r", "150", "-f", "1", "-l", str(max_pages),
                 str(target), prefix],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except FileNotFoundError:
            return [], "pdftoppm not found — install poppler-utils"
        except subprocess.TimeoutExpired:
            return [], "rasterization timed out"
        if result.returncode != 0:
            return [], result.stderr.strip() or f"pdftoppm exited with code {result.returncode}"

        images = []
        for i, p in enumerate(sorted(Path(tmp).glob("page-*.png")), start=1):
            data = base64.b64encode(p.read_bytes()).decode()
            images.append({"mime": "image/png", "data_b64": data, "source": f"{target.name}#page={i}"})
        return images, None


def execute(args: dict) -> dict:
    path_arg = args.get("path")
    if not path_arg:
        return {"error": "'path' is required"}
    target = Path(path_arg).expanduser().resolve()
    if not target.exists():
        return {"error": f"file not found: {target}"}
    if target.suffix.lower() != ".pdf":
        return {"error": f"not a PDF: {target}"}

    max_pages = args.get("max_pages", 10)
    if not isinstance(max_pages, int) or max_pages < 1:
        return {"error": "'max_pages' must be a positive integer"}

    text = _extract_text(target)
    if text is not None and len(text.strip()) >= _MIN_TEXT_LENGTH:
        return {"_attachment": True, "images": [], "text": text}

    images, err = _rasterize(target, max_pages)
    if err:
        return {"error": err}
    return {"_attachment": True, "images": images, "text": text}
