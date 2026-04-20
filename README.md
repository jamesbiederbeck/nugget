# Nugget

A CLI chat interface for a locally-hosted Gemma 4 model. 

Why Nugget? Because it's a small, tasty way to interact with your local LLM. It's designed to be simple and intuitive, with a focus on tool use and "thinking" (chain-of-thought reasoning). It's not trying to be a full-featured chat client or knowledge management system -- just a quick and easy way to ask questions, run commands, and take notes with your local model.

Also "gem" was already coined by the Gemma team, and "nugget" felt like a fun extension of that.

By default, we use a model from https://huggingface.co/collections/TrevorJS/gemma-4-uncensored. It's running locally, so why should it tell you no? Gemma 4 models in that collection have been [ablierterated](https://huggingface.co/blog/mlabonne/abliteration) to remove the "refusal" activation from their vocabulary, making them more cooperative and less likely to refuse requests. You can use any model you like, but these are a good starting point. The `-E4B` variant is a smaller, faster model with good reasoning abilities. See https://github.com/matt-c1/llama-3-quant-comparison as an example of the trade offs. You generally want a large quantization for more output quality, or a smaller one for more speed, but the selection is generally good, and the nuance of quantization levels is deep and outside the scope of this project.

## Requirements

- Python 3.11+
- A running textgen server (default: `http://127.0.0.1:5000`)

## Usage

```bash
# Interactive session
python -m gemma

# One-shot
python -m gemma "what is the capital of france"

# One-shot, no interactive follow-up
python -m gemma -n "summarize this" < file.txt

# Resume a session
python -m gemma --session my-session

# List saved sessions
python -m gemma --list-sessions

# Enable thinking
python -m gemma --thinking "explain backpropagation"
python -m gemma --thinking-effort 3 "hard problem"

# Verbose (show thinking, tool calls, system prompt)
python -m gemma -v "what time is it"
```

## Tools

| Tool | Description |
|------|-------------|
| `calculator` | Evaluate math expressions |
| `datetime` | Get current date/time |
| `shell` | Run shell commands (asks for approval) |
| `filebrowser` | Read and list files |
| `memory` | Persist notes across sessions |

```bash
# Filter tools
python -m gemma --include-tools calculator,datetime
python -m gemma --exclude-tools shell
python -m gemma --list-tools
```

## Configuration

Config lives at `~/.config/gemma/config.json`. Created automatically on first run.

| Key | Default |
|-----|---------|
| `api_url` | `http://127.0.0.1:5000` |
| `model` | `gemma-4-E4B-it-uncensored-Q4_K_M.gguf` |
| `temperature` | `0.7` |
| `max_tokens` | `2048` |
| `thinking_effort` | `0` (0=off, 1=low, 2=medium, 3=high) |
| `sessions_dir` | `~/.local/share/gemma/sessions` |

## Docker

```bash
docker build -t nugget .
docker run -it --network host nugget

# One-shot
docker run --network host nugget -n "what is 2+2"
```

`--network host` lets the container reach your model server at `127.0.0.1:5000`.

## Approval

Tool calls are governed by approval rules. By default, `shell` prompts before running; everything else is auto-allowed. Rules can be customized in `config.json`:

```json
"approval": {
  "default": "allow",
  "rules": [
    { "tool": "shell", "action": "ask" },
    { "tool": "memory", "args": { "operation": "delete" }, "action": "ask" }
  ]
}
```

## Roadmap
- [x] Basic chat interface
- [x] Tool calling framework
- [x] Thinking (chain-of-thought)
- [ ] Session management --partial; logs are saved, but sessions can't be resumed yet
- [ ] Semantic search over past conversations and memory