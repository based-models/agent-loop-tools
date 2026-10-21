# Native web search

`native_web_search()` creates an `agentloop.HostedTool` for a provider to execute.
Pass it in an `Agent`'s `tools` list. The provider searches, while `agentloop`
records the search result in the conversation transcript.

## Run an agent with search

Install `based-models-agentloop-tools` and the agentloop extra for your provider, as
shown in the [README](../README.md#installation). Set the provider's API key in your
environment. This example uses OpenAI Responses; Anthropic Messages also supports
native web search.

```python
import os

from agentloop import Agent, Transcript, final_text
from agentloop_tools.web import native_web_search

search = native_web_search(allowed_domains=["python.org"])
transcript = Transcript()
transcript.add_user_message(
    "Search the Python documentation and explain how to create a virtual environment."
)

with Agent.from_env(
    {**os.environ, "LLM_PROVIDER": "openai"},
    tools=[search],
    system="Use web search before answering. Cite the pages you use. Answer in one sentence.",
) as agent:
    agent.converse(transcript)

print(final_text(transcript))
```

Output:

```text
According to the Python docs, create a virtual environment by running `python -m venv .venv` in your project directory, then activate it with `source .venv/bin/activate` on macOS/Linux or `.venv\Scripts\activate.bat` / `.venv\Scripts\Activate.ps1` on Windows; the environment is isolated from the base Python by default and `pip` is bootstrapped unless you pass `--without-pip`. ([docs.python.org](https://docs.python.org/3/library/venv.html))
```

For OpenAI, use the Responses API, which is the default. Setting
`OPENAI_API=completions` makes hosted search unavailable. OpenRouter, Modal/vLLM,
and other Chat Completions providers do not support this hosted tool.

## Configure search

```python
from agentloop_tools.web import native_web_search

search = native_web_search(
    allowed_domains=["python.org"],
    search_context_size="medium",
)
print(search.kind)
print(search.options)
```

Output:

```text
web_search
{'allowed_domains': ['python.org'], 'search_context_size': 'medium'}
```

| Option | Meaning | Anthropic | OpenAI Responses |
| --- | --- | --- | --- |
| `allowed_domains` | Include only these hosts or paths | Supported | Supported |
| `blocked_domains` | Exclude these hosts or paths | Supported | Supported |
| `user_location` | Approximate city, region, country, or timezone | Supported | Supported |
| `max_uses` | Limit searches per request | Supported | Ignored with a warning |
| `dynamic_filtering` | Filter results with provider-side code, Claude 4.6+ | Supported | Ignored with a warning |
| `search_context_size` | Set how much search content reaches the model | Ignored with a warning | Supported |

Use either `allowed_domains` or `blocked_domains`. Passing both raises `ValueError`.
Domain entries are bare ASCII hosts, optionally followed by a path such as
`example.org/reports`; schemes such as `https://` are rejected. A host rule also
covers its subdomains. `*` is allowed in paths, but not in hostnames.

`dynamic_filtering` defaults to `False`. Anthropic's basic search can preserve
citations. With Claude 4.6 or later, dynamic filtering runs provider-side code on
results, which can leave the answer without citation blocks. It is not eligible for
Zero Data Retention. See [sources and citations](evidence.md) for reading both forms
of evidence.
