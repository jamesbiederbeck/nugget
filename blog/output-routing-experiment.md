# Teaching a Local LLM Where to Put Its Output

When you're running a tool-calling LLM locally, you run into a problem that cloud APIs mostly hide from you: where does the tool output go?

With a cloud assistant, the model calls a tool, gets a result, and the platform handles display. With a local model you're building the whole stack yourself, so you have to answer the question explicitly: does the tool result go back into the model's context? Get printed to the terminal? Written to a file? Piped into another tool?

For [Nugget](https://github.com/victorbiederbeck/nugget) — a CLI chat interface for locally-hosted models — I implemented what I called *output routing*: a convention where the model includes an `output` argument on any tool call to declare where the result should go.

```
output: "display"        → show the result to the user, don't add it to context
output: "file:/tmp/x"   → write the result to a file
output: "$varname"       → bind to a variable for use in a later call
(no output arg)          → return result inline into the model's context
```

The design is simple enough. Whether the model actually uses it is another question.

## Approach 1: The model tags every tool call

The first approach asks the model to include `output: "display"` directly on every tool call where it wants the result shown. The system prompt explains the convention and gives examples. When the model calls wallabag to fetch an article and wants to show it, it's supposed to write:

```
<tool_call>call:wallabag{article_id:183, output:"display"}</tool_call>
```

To measure how reliably this works, I built a prompt compliance bench — a TSV of test cases, each with a prompt, a set of tools, and one or more assertions about the model's first tool call. Each assertion specifies a *target* (a dot-path into the tool call, like `tool_call[0].args.output`) and a *constraint* (a regex, an absent/present check, etc.).

Running the full suite against the model with real tool execution:

**20/26 passed (76.9%)**

Running it again with tool execution mocked out (so results don't influence second-turn behavior):

**23/26 passed (88.5%)**

The gap between real and mock runs is itself informative — some failures in the real run happened because seeing the actual wallabag response changed the model's second-turn routing decision. Mocking isolates first-intent, which is what the bench is actually trying to measure.

The persistent failures in the mock run:

| Case | Prompt | Expected output arg | Got |
|------|--------|-------------------|-----|
| `display_natural` | "Show me wallabag article 183" | `^display` | `None` |
| `shell_display` | "Run ls /tmp and show me the output" | `^display` | `None` |
| `var_bind` | "Fetch article 183, bind it to $art, show me the title" | `^\$` | `None` |

The pattern: natural language display requests ("show me", "read me") reliably trigger the right tool but don't reliably trigger the output routing annotation. The model calls wallabag and gets the result inline instead of routing it to display. It doesn't fail to understand the task — it just doesn't connect "show me" to the routing protocol.

File routing, interestingly, is nearly perfect. When a prompt says "save it to `file:/tmp/x.json`", the model correctly emits `output: "file:/tmp/x.json"` almost every time. The path literal in the prompt is a strong enough signal. "Display" doesn't have an equivalent surface form in natural language.

## Approach 2: A dedicated dispatch tool

The hypothesis for the second approach: instead of asking the model to annotate every tool call with routing metadata, give it a single tool whose *name* communicates intent.

```python
render_output(tool_name: str, tool_args: object, output: str)
```

The model calls `render_output` when it wants to route a result somewhere. It doesn't need to remember to tag the domain tool — it just picks the right dispatch tool for the job.

This is a different cognitive load. "Remember to add `output: display` to this call" is procedural overhead on top of the primary task. "Use render_output when you want to show something" is a tool-selection decision, which is already how the model decides what to call.

I wrote a parallel bench suite with 16 cases against the same prompts, this time with `render_output` in the tools list alongside the domain tools. Schema description:

> *"Call any tool and send its output somewhere. Use this when you want to display a tool's result to the user, save it to a file, or bind it to a variable — instead of calling the tool directly and receiving the result inline."*

**12/16 passed (75%)** — but the raw number is misleading. Look at where it passed and failed:

| Assertion | Result | Notes |
|-----------|--------|-------|
| `tool_call[0].name == "render_output"` | **3/3 PASS** | Display cases: model reached for render_output every time |
| `tool_call[0].args.tool_name == "wallabag"` | **3/3 PASS** | Wrapped tool correctly identified |
| `tool_call[0].args.output =~ ^display` | **0/3 FAIL** | Model omitted the output arg entirely |
| `tool_call[0].args.output =~ ^file:` | **1/1 PASS** | File routing still works |
| `tool_call[0].name == "calculator"` (no render_output) | **1/1 PASS** | Pure reasoning: went direct |

The model correctly reached for `render_output` for every natural display case. It correctly identified the wrapped tool. It correctly added the `output` arg for file routing. The only thing it consistently didn't do: include `output: "display"` on render_output calls.

That's not a failure. That's the model telling us something.

## What the model is actually saying

When the model calls `render_output(tool_name="wallabag", tool_args={...})` with no `output` arg, it's treating the tool name as the routing declaration. "I called the render tool. Why would I also need to say display? That's what render means."

The implication for the design: `output` on `render_output` should be optional, defaulting to display. The revised API:

```
render_output(tool_name, tool_args)                      → display (default)
render_output(tool_name, tool_args, output="file:/tmp/x") → file
render_output(tool_name, tool_args, output="$var")        → variable binding
```

This matches observed behavior exactly. File routing works because there's a concrete path in the prompt that maps to the `output` arg. Display works because the model treats render_output itself as the display intent. Variable binding should work for the same reason file routing does — there's a surface-form token (`$var`) that the model can attach.

The one case that arguably fails: "What is the title of article 183?" called `render_output` when the expected behavior was a direct `wallabag` call with the result inline. But `render_output(tool_name="wallabag", ...)` with no output arg and a default-display behavior isn't obviously wrong for a lookup question — it just puts the result on display instead of in context. Whether that's a bug depends on how you want the conversation to flow.

## Comparison

| | Approach 1 (output arg) | Approach 2 (render_output) |
|---|---|---|
| File routing | ✅ Reliable | ✅ Reliable |
| Display (explicit) | ✅ Reliable | ✅ Reliable |
| Display (natural language) | ❌ 0–1/3 | ✅ 3/3 |
| Variable binding | ❌ Misses | TBD |
| "Right tool" identification | ✅ Always correct | ✅ Always correct |
| Design burden on model | High (metadata on every call) | Low (tool-selection decision) |

The fundamental difference: approach 1 requires the model to perform a mechanical annotation step on top of every tool call. Approach 2 converts routing into a tool-selection decision, which is the kind of reasoning the model is already doing.

The bench scores aren't that far apart — 88.5% vs 75% raw — but the failure modes are structurally different. Approach 1 misses on natural language display. Approach 2 misses on an `output` arg the model evidently doesn't think it needs to provide. One of those is a design problem worth fixing; the other is evidence that the design is already right.

## What's next

The next step is implementing `render_output` properly: a tool that dispatches to any registered tool in the registry and routes the result through the existing output sink mechanism. The `output` arg is optional; absent means display. The bench cases get updated to test `tool_call[0].name == "render_output"` and `tool_call[0].args.tool_name` rather than annotated domain calls, and we rerun to confirm.

The deeper question the experiment surfaces: if the model now has `render_output` available and defaults to using it for most tool calls, does that change how we think about when domain tools should be called directly? There may be a cleaner split — domain tools for inline results, `render_output` for anything that leaves the context — and the model may already be navigating toward it without being told.
