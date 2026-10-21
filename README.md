# based-models-agentloop-tools

`based-models-agentloop-tools` provides typed, validated tools for
`based-models-agentloop` agents. Its first tool family makes provider-hosted web search easy
to configure, limits where searches may go, and extracts the sources and citations behind an
answer.

The package is installed as `based-models-agentloop-tools` and imported as
`agentloop_tools`. It requires Python 3.12 or newer.

## Why use agentloop-tools?

- Add native Anthropic or OpenAI web search to an `Agent` with one tool factory.
- Validate domain filters, location data, search limits, and provider options before a
  request is sent.
- Apply one allowlist or blocklist both to the provider request and to a post-response audit.
- Recover deduplicated search sources and ordered answer citations from a transcript.
- Detect disallowed domains in search results, citations, URLs, Markdown links, and blocked
  host names written in an answer.
- Keep configuration and credentials in the application; this package never reads the
  environment.
- Stay provider-light: the package depends only on `based-models-agentloop` and imports only
  its public API.

## Installation

Install this package together with the extra for the provider your agent uses.

For Anthropic:

```bash
pip install based-models-agentloop-tools "based-models-agentloop[anthropic]"
```

For OpenAI:

```bash
pip install based-models-agentloop-tools "based-models-agentloop[openai-compat]"
```

Native web search works with Anthropic Messages and the OpenAI Responses API. OpenAI uses
Responses by default once `LLM_PROVIDER=openai` is selected; it will not work when
`OPENAI_API=completions` is selected. OpenRouter, Modal/vLLM, and other Chat
Completions-compatible providers do not offer this hosted tool.

## Quick start

Create a hosted search tool, pass it to `Agent`, and use a `Transcript` when you want to
inspect the evidence:

```python
import os

from agentloop import Agent, Transcript, final_text
from agentloop_tools.web import citations, native_web_search, sources

search = native_web_search(
    allowed_domains=["python.org"],
)

transcript = Transcript()
transcript.add_user_message(
    "Search the Python documentation and explain how to create a virtual environment."
)

with Agent.from_env(
    {**os.environ, "LLM_PROVIDER": "openai"},
    tools=[search],
    system="Use web search before answering. Cite the pages you use.",
) as agent:
    agent.converse(transcript)

print(final_text(transcript))

for source in sources(transcript):
    print("searched:", source.url)

for citation in citations(transcript):
    print("cited:", citation.url)
```

The provider performs the search. `agentloop` records the search activity, sources,
citations, and provider replay data in the transcript; this package provides the validated
configuration and evidence readers.

## Native web search options

```python
from agentloop_tools.web import native_web_search

search = native_web_search(
    allowed_domains=["europa.eu", "oecd.org/ai"],
    max_uses=3,
    user_location={
        "city": "Brussels",
        "country": "BE",
        "timezone": "Europe/Brussels",
    },
    search_context_size="high",
)
```

| Option | Meaning | Anthropic | OpenAI Responses |
|---|---|---:|---:|
| `allowed_domains` | Search only these domains and paths | Yes | Yes |
| `blocked_domains` | Exclude these domains and paths | Yes | Yes |
| `user_location` | Approximate city, region, country, or timezone | Yes | Yes |
| `max_uses` | Maximum searches per request | Yes | Ignored with a warning |
| `dynamic_filtering` | Filter results with provider-side code (Claude 4.6+) | Yes | Ignored with a warning |
| `search_context_size` | Amount of search content supplied to the model | Ignored with a warning | Yes |

Unknown options are rejected. Unsupported domain restrictions are never silently dropped;
unsupported tuning options are logged and ignored by the adapter.

### Domain validation

Domain filters use bare ASCII domains without a URL scheme:

```python
native_web_search(allowed_domains=["europa.eu", "example.com/reports"])
```

- Pass either `allowed_domains` or `blocked_domains`, never both. Passing both raises
  `ValueError`.
- A rule includes the named host and its subdomains.
- An optional path restricts the rule to that path prefix.
- `*` is allowed within a path, but not in a hostname.
- Schemes such as `https://` are rejected.
- Non-ASCII domains are rejected to prevent look-alike Unicode domains from bypassing a
  filter.

## Sources and citations

The two evidence readers serve different purposes:

```python
from agentloop_tools.web import citations, sources

searched_pages = sources(transcript)
cited_claims = citations(transcript)
```

- `sources(transcript)` returns every page a hosted search consulted, deduplicated by URL in
  first-appearance order.
- `citations(transcript)` returns every citation attached to assistant text, in transcript
  order.

A source shows what the provider searched. A citation ties part of the generated answer to a
page. They are related but not interchangeable: a provider may search a page without citing
it, and not every search mode produces citations.

### Anthropic dynamic filtering

`dynamic_filtering=False` is the default because Anthropic's basic search preserves
citations. With Claude 4.6 or later, enabling it runs provider-side code to filter
results before they reach the model. This can help search-heavy requests, but it has
important tradeoffs:

- `sources()` still returns the pages consulted.
- `citations()` may be empty because the model reads the filtering program's output rather
  than citation-bearing search-result blocks.
- The mode is not eligible for Zero Data Retention.

OpenAI ignores `dynamic_filtering` with a warning.

## Domain policy: prevent, then audit

`DomainPolicy` keeps one allowlist or blocklist as the source of truth for both request-time
filtering and response-time auditing.

```python
import os

from agentloop import Agent, Transcript, final_text
from agentloop_tools.web import DomainPolicy

policy = DomainPolicy.allow(["python.org"])
search = policy.native_web_search()

transcript = Transcript()
before = len(transcript.messages)
transcript.add_user_message(
    "Search the Python documentation and explain how to create a virtual environment."
)

with Agent.from_env(
    {**os.environ, "LLM_PROVIDER": "openai"},
    tools=[search],
    system="Use web search before answering. Cite the pages you use.",
) as agent:
    agent.converse(transcript)

violations = policy.audit(transcript, since=before)
if violations:
    for violation in violations:
        print(violation.where, violation.url, violation.rule)
else:
    print(final_text(transcript))
```

Construct policies with one of:

```python
allowed = DomainPolicy.allow(["python.org"])
blocked = DomainPolicy.block(["example.com", "example.org/private"])
```

`policy.native_web_search()` sends the policy's domains to the provider. `policy.audit()`
then inspects completed assistant messages for:

- Sources returned by hosted search
- Citations attached to assistant text
- Full URLs, including Markdown link targets, written in the answer
- Bare mentions of blocked hosts in block mode

Each `Violation` reports the URL or mention, where it appeared, the transcript message index,
and the matching block rule when applicable. Auditing does not modify the transcript, raise
an exception, retry the request, or choose an enforcement response; the application decides
whether to log, reject, re-ask, or warn the user.

### Policy limits

Native search runs inside the provider's response. A domain filter asks the provider not to
return a domain, but downstream code cannot prevent the model from reading a page that the
provider did return. `DomainPolicy` therefore follows a deliberate two-stage model:

1. Prevent what the provider can prevent with its native domain filter.
2. Report disallowed domains that still appear in sources, citations, or answer text.

In allow mode, the audit checks full URLs but does not treat every host-like word as a domain;
doing so would create false positives for text such as `config.py`. In block mode, it can
also look specifically for bare mentions of the configured blocked hosts.

## API overview

Import web tools explicitly from `agentloop_tools.web`:

```python
from agentloop_tools.web import (
    DomainPolicy,
    Violation,
    citations,
    native_web_search,
    sources,
)
```

- `native_web_search(...)` builds a validated `HostedTool` for provider-run search.
- `sources(transcript)` extracts unique consulted pages.
- `citations(transcript)` extracts citations attached to assistant text.
- `DomainPolicy.allow(...)` and `DomainPolicy.block(...)` create domain policies.
- `policy.native_web_search(...)` builds a search tool using the policy's domain list.
- `policy.match(...)` identifies the matching rule for a URL or hostname.
- `policy.permits(...)` checks whether a URL or hostname is allowed.
- `policy.audit(...)` returns policy violations without mutating the transcript.

Tool families are intentionally imported explicitly rather than re-exported from the package
root. The package uses only `agentloop`'s public API and never reads configuration, API keys,
or environment variables.

This release provides provider-hosted web search. Client-side search, where your own Python
tool calls a search API and controls results before the model sees them, is a separate feature
and is not included yet.

## Documentation

Read the [documentation](https://www.basedmodels.com/docs/agent-tools) for
the [hosted search guide](https://www.basedmodels.com/docs/agent-tools/native-web-search),
[sources and citations](https://www.basedmodels.com/docs/agent-tools/evidence),
and [domain policies](https://www.basedmodels.com/docs/agent-tools/domain-policy).
It builds on [agentloop](https://www.basedmodels.com/docs/agent-loop), which this version
requires at `0.5.x`.

## Stability and license

`based-models-agentloop-tools` is currently beta software. While the version is `0.x`, a
minor release may change the public API.

Licensed under the Apache License 2.0.
