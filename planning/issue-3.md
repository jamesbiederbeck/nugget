# Issue 3 — Model compliance failures: output routing, hallucinated args, re-spawn instead of recall

**Status:** open  
**Surface:** `src/nugget/templates/system.j2`, `src/nugget/tools/spawn_agent.py` (SCHEMA description)  
**Type:** model-compliance / system prompt deficiency  
**Sessions:** b3077b8b, d0b46965  
**Related feature:** see ROADMAP items #18, #19 (structured generation, forced thinking injection)

---

## Observed failures

### 1. `spawn_agent` — `output` binding not generated (session d0b46965, bench `subagent_output.output` 0/1)

When asked to bind a `spawn_agent` result to `$child`, the model omits the `output` arg entirely. The logprobs probe reveals why:

```
token [35]: ',' 57.4%  vs  '}' 42.6%   ← whether to add another arg at all
token [36]: 'return_thinking' 87.2%  vs  'output' 12.2%
```

If the model decides to add an arg (57% of the time), it overwhelmingly generates `return_thinking` — a hallucinated key not in the schema — rather than `output`. The `output` routing instruction in the system prompt is generic; `spawn_agent`'s schema description says nothing about it. The model does not connect the two.

### 2. `spawn_agent` — re-spawn instead of recall (session d0b46965 turn 2)

After a completed `spawn_agent` turn, when the user asks "what did its thinking block look like?", the model calls `spawn_agent` again instead of answering from the existing result in context:

```
token [0]: '<|tool_call>' 85.6%  vs  'Since' (prose) 11.9%
```

Once it chooses a tool call, `spawn_agent` is 99.9% likely and `return_thinking:true` is generated at 94.3% — a hallucinated arg the model invented to request thinking it cannot actually retrieve.

The model has no guidance that spawn_agent results are already in context and need no re-query.

### 3. `spawn_agent` not called at all (session b3077b8b)

Earlier session where `spawn_agent` was not in the tool list (tool was not yet deployed). Model roleplayed the subagent response inline instead of erroring or asking. Not a current code bug — resolved when `spawn_agent` shipped — but documented here as context for the tooling gap (no schema enforcement means hallucinated calls look identical to real ones until the executor rejects them).

---

## Root causes

| Failure | Root cause |
|---|---|
| Missing `output` on `spawn_agent` | Schema description does not mention that `output` routing applies to this tool |
| Re-spawn instead of recall | No system prompt guidance for "answer from existing spawn_agent result in context" |
| `return_thinking` hallucination (both failures) | No schema constraint; model learned the pattern from training. At 87–94% confidence, cannot be fixed by temperature alone |

---

## Immediate mitigations (low-effort)

1. Add `output` to `spawn_agent`'s schema `description` field: `"output: (optional) route the answer — '$var' to bind for later use, 'display' to show directly to the user."` This shifts the logit distribution at the arg-name decision.

2. Add a note to the spawn_agent result format (in `system.j2` or in `spawn_agent`'s description) that the answer is returned in the tool response and should not be re-queried.

---

## Longer-term fix

See ROADMAP items #18 and #19:
- **#18 — Structured generation**: grammar-constrained decoding during tool arg generation; rejects hallucinated keys at sampling time, making `return_thinking` impossible to emit.
- **#19 — Forced thinking injection**: keyword-triggered reasoning prefix injected before critical decisions; logprob probes suggest this can shift `output` from 12% to dominant probability when the thinking block names it explicitly.

---

## Bench coverage

New cases added in `bench/cases/subagent.tsv`:
- `subagent_no_hallucinated_args.no_return_thinking` — asserts `return_thinking` absent from args
- `subagent_recall.no_respawn` — asserts no tool call when answer is in context

Both pass in the most recent mock-tools bench run (`subagent_20260503`). The `subagent_output.output` case remains 0/1.
