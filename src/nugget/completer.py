"""
SlashCommandCompleter — prompt_toolkit Completer for /commands.
Only activates when the input is a bare slash-prefixed token (no space yet).
"""

from prompt_toolkit.completion import Completer, Completion


class SlashCommandCompleter(Completer):
    def __init__(self, command_descriptions: dict[str, str]) -> None:
        self._commands = command_descriptions

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/") or " " in text:
            return
        for name, desc in sorted(self._commands.items()):
            if name.startswith(text):
                yield Completion(
                    name,
                    start_position=-len(text),
                    display=name,
                    display_meta=desc,
                )
