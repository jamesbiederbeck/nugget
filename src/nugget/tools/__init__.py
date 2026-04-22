"""
Tool registry — auto-discovers all .py submodules in this package.

Each tool module must expose:
  SCHEMA: dict   — OpenAI-style function tool schema
  execute(args: dict) -> object
"""

import importlib
import pkgutil
from pathlib import Path
from typing import Callable


_registry: dict[str, tuple[dict, Callable]] = {}
_gates: dict[str, str | Callable | None] = {}


def _load_all() -> None:
    if _registry:
        return
    pkg_dir = Path(__file__).parent
    for info in pkgutil.iter_modules([str(pkg_dir)]):
        mod = importlib.import_module(f"{__name__}.{info.name}")
        if hasattr(mod, "SCHEMA") and hasattr(mod, "execute"):
            name = mod.SCHEMA["function"]["name"]
            _registry[name] = (mod.SCHEMA, mod.execute)
            _gates[name] = getattr(mod, "APPROVAL", None)


def all_tools() -> dict[str, tuple[dict, Callable]]:
    _load_all()
    return dict(_registry)


def schemas(include: list[str] | None = None, exclude: list[str] | None = None) -> list[dict]:
    _load_all()
    names = set(_registry.keys())
    if include is not None:
        names = names & set(include)
    if exclude is not None:
        names = names - set(exclude)
    return [_registry[n][0] for n in sorted(names)]


def execute(name: str, args: dict) -> object:
    _load_all()
    if name not in _registry:
        return {"error": f"unknown tool: {name}"}
    try:
        return _registry[name][1](args)
    except Exception as e:
        return {"error": str(e)}


def gate(name: str) -> str | Callable | None:
    _load_all()
    return _gates.get(name)


def list_names() -> list[str]:
    _load_all()
    return sorted(_registry.keys())
