from typing import Protocol, Callable, runtime_checkable


class BackendError(Exception):
    pass


@runtime_checkable
class Backend(Protocol):
    def run(
        self,
        messages: list[dict],
        tool_schemas: list[dict],
        tool_executor: Callable[[str, dict], object],
        system_prompt: str,
        **kwargs,
    ) -> tuple[str, str | None, list[dict]]: ...


def make_backend(config) -> Backend:
    name = config.get("backend", "textgen")
    if name == "textgen":
        from .textgen import TextgenBackend
        return TextgenBackend(config)
    raise ValueError(f"unknown backend: {name!r}")
