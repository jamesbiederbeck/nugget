#!/usr/bin/env bash
# Test curl for local Gemma API — raw completions with native Gemma 4 tokens
set -euo pipefail

BASE="http://127.0.0.1:5000"
COMP="$BASE/v1/completions"
H='Content-Type: application/json'

hr() { echo; echo "=== $* ==="; }

hr "List models"
curl -s "$BASE/v1/models" | python3 -m json.tool

hr "Simple completions"
curl -s "$COMP" -H "$H" -d '{
  "prompt": "<|turn>system\nYou are a helpful assistant.<turn|>\n<|turn>user\nSay hi in 5 words.<turn|>\n<|turn>model\n",
  "max_tokens": 32, "temperature": 0.7, "stop": ["<turn|>"]
}' | python3 -m json.tool

hr "Thinking mode (low effort)"
curl -s "$COMP" -H "$H" -d '{
  "prompt": "<|turn>system\n<|think|>Think briefly.<turn|>\n<|turn>user\nWhat is 144 / 12?<turn|>\n<|turn>model\n",
  "max_tokens": 1024, "temperature": 0.7, "stop": ["<turn|>"]
}' | python3 -m json.tool

hr "Tool declaration + call (stop before tool_response)"
curl -s "$COMP" -H "$H" -d '{
  "prompt": "<|turn>system\nYou are a helpful assistant.<|tool>declaration:calculator{description:<|\"|>Evaluate a math expression<|\"|>,parameters:{type:<|\"|>object<|\"|>,properties:{expression:{type:<|\"|>string<|\"|>,description:<|\"|>math expression<|\"|>}},required:[<|\"|>expression<|\"|>]}}<tool|><turn|>\n<|turn>user\nWhat is 7 * 8? Use the calculator.<turn|>\n<|turn>model\n",
  "max_tokens": 128, "temperature": 0.7, "stop": ["<turn|>", "<|tool_response>"]
}' | python3 -m json.tool

hr "Full tool loop (injected tool response, model finalizes)"
curl -s "$COMP" -H "$H" -d '{
  "prompt": "<|turn>system\nYou are a helpful assistant.<|tool>declaration:calculator{description:<|\"|>Evaluate a math expression<|\"|>,parameters:{type:<|\"|>object<|\"|>,properties:{expression:{type:<|\"|>string<|\"|>,description:<|\"|>math expression<|\"|>}},required:[<|\"|>expression<|\"|>]}}<tool|><turn|>\n<|turn>user\nWhat is 7 * 8? Use the calculator.<turn|>\n<|turn>model\n<|tool_call>call:calculator{expression:<|\"|>7 * 8<|\"|>}<tool_call|><|tool_response>response:calculator{result:<|\"|>56<|\"|>}<tool_response|>",
  "max_tokens": 64, "temperature": 0.7, "stop": ["<turn|>", "<|tool_response>"]
}' | python3 -m json.tool
