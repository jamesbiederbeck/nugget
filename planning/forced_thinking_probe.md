# Forced Thinking Injection — Logprob Probe Results

**Date:** 2026-05-03  
**Model:** gemma-4-E4B-it-uncensored-Q4_K_M.gguf  
**Related issue:** `planning/issue-3.md`  
**Related roadmap item:** ROADMAP #19

## Method

For each failure case, two probes were run:

1. **Baseline** — prompt stopped at the critical decision token; `max_tokens=1, logprobs=10`.
2. **Forced thinking** — a short reasoning prefix injected into the model turn before the decision token, then same single-token probe.

The injection format uses Gemma 4's native thinking channel:

```
<|channel>thought
... reasoning text ...
<channel|>
```

This is valid model output (not a prompt injection) and is already used by the thinking feature. The hypothesis is that explicit reasoning shifts the logit distribution before the decision token is sampled.

---

## Probe A — `spawn_agent` output binding (`$child`)

**Scenario:** User asks to bind `spawn_agent` result to `$child`. Probe point: the token immediately after the `task` arg value closes — will the model add `,output:` or close with `}`?

### Baseline (no thinking)

```
'}'    75.7%   ← closes without output arg (wrong)
','    24.3%   ← would add another arg
```

If comma is sampled (24% of runs), the key chosen next is `return_thinking` at 87% vs `output` at 12%. Combined probability of correct `output` arg: ~3%.

### Forced thinking injected

Injected text: *"The user wants the result bound to $child. I must include output:'$child' in the spawn_agent call so the harness stores the answer in that variable."*

```
','    94.8%   ← will add another arg (massive flip from 24% → 95%)
'}'     5.2%
```

After comma:
```
'output'         86.3%   ← correct (was 12% baseline — 7× improvement)
'return_thinking'  9.1%   ← hallucinated key (was 87% baseline)
'context'          2.4%
'tools'            2.1%
```

**Result: combined probability of generating `output` arg goes from ~3% to ~82%.**

---

## Probe B — Recall vs re-spawn

**Scenario:** Prior `spawn_agent` exchange in context; user asks "what did its thinking block look like?". Probe point: first token of the model's response turn.

### Baseline

```
'<|tool_call>'   84.5%   ← re-spawns agent (wrong)
'Since'          12.7%   ← prose answer (correct)
'The'             1.6%
```

### Forced thinking injected

Injected text: *"The user is asking about the subagent's thinking block. But looking at the spawn_agent result in context, it only returned {answer:..., tool_calls:0, finish_reason:stop} — there is no thinking field. The subagent did not produce a thinking block. I should tell the user that directly rather than spawning another agent."*

```
'The'    71.0%   ← prose answer (was 1.6% baseline — 44× improvement)
'Based'  11.0%
'It'      7.6%
'In'      3.5%
'Since'   2.5%
```

**`<|tool_call>` drops off the top-6 entirely. Result: model answers from context instead of re-spawning.**

---

## Probe C — `render_output` keyword trigger ("route output to display")

**Scenario:** User says "route the output of wallabag article 42 to display". Two sub-probes: (1) does the model call a tool at all, (2) does it set `output:'display'`?

### First token — baseline vs forced

```
Baseline:        '<|tool_call>'  99.99%   (already correct — no problem here)
Forced thinking: '<|tool_call>'  99.20%   (no regression)
```

The model already calls a tool for this phrasing. The problem is what it puts in `output`.

### `output` value — after forced thinking

Probe point: key name after `tool_args:{...},` inside the render_output call.

```
'output'   100.0%   ← correct (forced thinking makes this absolute)
```

**Result: forced thinking locks `output` to 100% for the render_output routing case.**

---

## Summary

| Probe | Metric | Baseline | Forced thinking | Delta |
|---|---|---|---|---|
| A: spawn_agent output binding | P(correct `output` arg emitted) | ~3% | ~82% | +79pp |
| B: recall vs re-spawn | P(prose answer, no tool call) | ~15% | ~95% | +80pp |
| C: render_output keyword | P(`output` key correct) | unknown | 100% | — |

---

## Conclusion

Forced thinking injection is highly effective. A single short sentence naming the correct behavior shifts the probability distribution by 40–80 percentage points at the critical decision token. The mechanism is practical because:

1. It requires no model fine-tuning or weight changes.
2. The injection can be triggered deterministically at the harness level (keyword match in user message, or unconditionally before specific tool calls).
3. It uses native Gemma 4 thinking tokens — the model already understands this channel.
4. It can be benchmarked directly: add a `forced_thinking` column to bench case TSVs and compare pass rates.

**This makes ROADMAP #19 high-confidence.** The keyword-trigger approach (detect "bind to $var", "route output to", etc. → inject targeted thinking) can be implemented today with no backend changes.

**Combined with #18 (structured generation):** forced thinking steers the distribution toward the correct token; structured generation masks the wrong tokens as a hard constraint. Together they should bring `output` routing compliance to near-100%.
