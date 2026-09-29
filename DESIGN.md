# agentloop-tools: design record

The decisions behind this library and the agentloop 0.2 seam it depends on, with the
reason for each.

## Layers

```
harness          app: prompt, CLI, secrets, approval policy, WHICH tools are on
agentloop-tools  mechanism: tool factories, validation, readers
agentloop        the loop, the provider seam, transcript; no tools
```

Each layer depends only on the one below. This library imports agentloop's public API
(`agentloop.__all__`) and never reads configuration; `tests/test_layering.py` enforces
both rules.

## Native search is a HOSTED tool, so part of it lives in agentloop

The provider runs a native search, so the request must declare it and the transcript
must carry what came back. Only agentloop's adapters can do either. agentloop 0.2
therefore learned one generic idea, *hosted tools*, and nothing web-specific:

| agentloop (generic) | agentloop-tools (web-specific) |
|---|---|
| `HostedTool(kind, options)` on `ModelRequest.hosted_tools` | `native_web_search(...)`: typed, validated options |
| Each adapter translates `kind="web_search"` | Domain normalization; ASCII-only (homograph) check |
| `HostedToolPart`, `Source`, `Citation` (a readable view) | `sources(transcript)`, `citations(transcript)` |
| `StopReason.PAUSED` + loop continuation | |
| `Agent` refuses a hosted kind the client cannot run | |

Deliberately *not* in agentloop: no observer event (observers scan `on_response`), no
usage field (count the parts), no typed web options.

**Native and client search are separate first-class choices.** Neither is a fallback:
`Agent` raises, naming the provider, if the provider cannot run a hosted tool. Client
search is on agentloop's BACKLOG.

| | Native (`native_web_search`) | Client (backlog) |
|---|---|---|
| Who searches | The provider | Your code, through a search API |
| Providers | Anthropic, OpenAI Responses | All of them |
| What you see | Queries, URLs, citations; page text is encrypted | Full snippets, as a tool result |
| Approval | Per request: declare it or don't, plus domain filters | Per call, through `before_tool` |

## Replay: `Message.origin`

Both providers need the assistant turn sent back **exactly**:
- **Anthropic:** content blocks go back as received. Altering or omitting
  `encrypted_content` or a citation's `encrypted_index` returns a 400. Dynamic filtering
  adds code-execution blocks. A mixed client/server turn returns the search result in the
  *next* response.
- **OpenAI Responses:** `reasoning` items (with `encrypted_content`) and each message's
  `phase` must survive, in order.

Canonical parts cannot rebuild any of that. So each adapter stores its own wire form on
the message: `Origin(provider, api, model, raw)`.
- **Same `(provider, api)`:** the adapter replays `raw`.
- **Anything else:** it rebuilds from the parts and drops what cannot move (reasoning,
  hosted activity).

The parts are the portable view; `raw` is same-provider fidelity. Unknown block types
survive automatically. They used to be dropped silently.

The same mechanism implements OpenRouter reasoning replay. The Completions codec
reattaches `reasoning_details` from the origin, but rebuilds the message itself from
parts, because generated tool-call ids must match the results.

## OpenAI: Completions and Responses, one transport

`OpenAICompatClient` is the transport: auth, timeouts, HTTP errors, the non-JSON guard,
`close`. A `Codec` is the wire format: `path`, `request_to_wire`, `response_from_wire`,
`hosted_tools`.
- **`api="completions"`:** `/chat/completions`. OpenRouter, Modal, and OpenAI when asked.
  It refuses hosted tools rather than dropping them.
- **`api="responses"`:** `/responses`, OpenAI's default (`OPENAI_API`). This is where
  hosted search lives.

There is no duplicated transport and no mode flags inside the translators.

## Responses is stateless, always

Responses can hold the conversation server-side: `store` defaults to **true**, and there
are `previous_response_id` and Conversations. agentloop's `Transcript` is the single
source of truth: JSONL resume, discarded truncated turns, provider switching, and blind
retries of a pure `complete()`. A second history would drift from it.

So every request:
- sends `store: false` and never sends `previous_response_id`;
- resends the full transcript as `input`, as Completions and Anthropic already do;
- strips item `id`s on replay. With nothing persisted, an id makes the server look up an
  item that doesn't exist, and the request fails.

`web_search_call` items are not replayed; the message's `url_citation` annotations carry
the evidence.

## Option policy (every adapter)

- **Unknown option:** error.
- **Unsupported restriction** (a domain list): error, because dropping it would widen
  access.
- **Unsupported tuning** (`max_uses` on OpenAI, `search_context_size` on Anthropic):
  logged and ignored.

## Domain policy: prevent and report, nothing more

`DomainPolicy.block([...])` or `DomainPolicy.allow([...])` is one list with two jobs:

- **Prevent:** `policy.native_web_search()` sends the list to the provider as its search
  filter, on both providers.
- **Report:** `policy.audit(transcript, since=n)` lists every `Violation` where a finished
  turn still reached a domain the policy does not permit. It checks sources (a provider
  leak), citations, and the answer text.

It exists because a provider filter is not a guarantee. Mirrors, subdomain edge cases,
and the model's own knowledge all get past it. Live, with Wikipedia blocked, Claude still
wrote four Wikipedia URLs from memory when asked; the audit caught all four.

**The hard limit:** with native search the model reads the results inside the provider's
response. Nothing downstream can stop it reading a page; the policy can only prevent what
the provider filters and report what came out. The real guarantee belongs to client-side
search, which will call `policy.permits(url)` on each hit before the model sees it
(BACKLOG).

**Deliberately minimal:** it doesn't hide, redact, retry, raise, or touch the transcript.
Altering replayed search results would 400 on Anthropic anyway. What to do about a
violation is the developer's decision.

**Text-scan boundaries:**
- **Full URLs, in both modes:** markdown targets are included, and balanced parentheses
  are kept, as in Wikipedia's `_(programming_language)`.
- **Bare host mentions, in block mode only:** word-bounded per rule, so
  `notwikipedia.org` doesn't match.
- **Why allow mode skips bare hosts:** it would need a generic host pattern, which would
  also flag `config.py`.

## Live verification (September 2026)

Confirmed live against Anthropic (`claude-opus-5`), OpenAI Responses (`gpt-5.5`) and
OpenRouter (`openrouter/free`):

- **Anthropic:** search (run with dynamic filtering, then the default; see below). The follow-up turn replayed the encrypted
  results from `origin.raw` and was accepted. A successful code-execution result is an
  object, not an error; the parser was corrected to count only `*_error` / `error_code`.
- **OpenAI Responses:** search with sources and `url_citation`s. Follow-up turns
  replayed `message` items (with `phase`), omitting `web_search_call` items, with every
  id stripped under `store: false`, and were accepted. A `reasoning` item was replayed
  id-less in two later requests and accepted. Three parallel function calls and their
  outputs round-tripped.
- **Domain filters:** `blocked_domains=["wikipedia.org"]` was accepted AND honored by both
  providers: no Wikipedia source on a query it would normally dominate.
- **Option policy:** `max_uses` on OpenAI is logged and ignored, as designed.
- **OpenRouter:** a follow-up routed to a different upstream model accepted the replayed
  `reasoning_details`.
- **OpenAI errors:** an empty balance is a 429 with `type: insufficient_quota`,
  `code: credit_balance_exhausted`. It is now `InsufficientCredits` and not retried.

Not triggered live: an Anthropic `pause_turn` (a merged continuation is covered by fixtures).

## Anthropic `dynamic_filtering` is off by default, because it removes citations

`native_web_search(dynamic_filtering=False)` is the default, so the adapter sends basic
search (`web_search_20250305`). This was flipped after an experiment
(`claude-opus-5`, 2 questions × 3 variants, 6 requests):

| Variant | Citations | How the model saw results |
|---|---|---|
| `web_search_20260209`, dynamic filtering | 0, 0 | Printed output of a program it wrote |
| `web_search_20250305`, basic | 2, 3 | Search-result blocks |
| `web_search_20260209` + `allowed_callers: ["direct"]` | 2, 5 | Search-result blocks |

With filtering on, Claude runs code that calls the search and prints a filtered excerpt,
and it reads only that (encrypted) stdout. A citation must point at a search-result block
in context, so there is nothing to cite. The text arrives split where citations would
sit, each block with `citations: []`, and the model lists sources in prose instead.

- **It's the code path, not the tool version:** the direct-caller variant uses the same
  version and cites normally.
- **It didn't save tokens here:** single, simple searches cost slightly more input with
  filtering (13,300 vs 12,827).
- **What still works:** `sources()` is filled in every mode.
- **The trade-off:** filtering is worth turning on only for search-heavy work where
  citations aren't needed.
