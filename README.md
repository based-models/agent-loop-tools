# based-models-agentloop-tools

Tools for [`based-models-agentloop`](https://pypi.org/project/based-models-agentloop/)
agents. The import name is `agentloop_tools`. Today: native web search with validated
options, a domain policy, and helpers to read sources and citations back out of a transcript.

```bash
pip install based-models-agentloop-tools
```

```python
import os

from agentloop import Agent, Transcript, final_text
from agentloop_tools.web import native_web_search, sources

search = native_web_search(allowed_domains=["europa.eu"], max_uses=3)

transcript = Transcript()
transcript.add_user_message("What does the EU AI Act say about general-purpose models?")

with Agent.from_env(os.environ, tools=[search], system="Cite your sources.") as agent:
    agent.converse(transcript)

print(final_text(transcript))
for source in sources(transcript):
    print(source.url)
```

- `native_web_search(...)`: the provider runs the search (Anthropic and OpenAI).
- `DomainPolicy`: one source of truth for allowed or blocked domains.
- `sources(transcript)` / `citations(transcript)`: the evidence behind an answer.

Families are imported explicitly (`from agentloop_tools.web import ...`). This package uses
only `agentloop`'s public API and never reads configuration or the environment.
Licensed under the [Apache License 2.0](LICENSE).
