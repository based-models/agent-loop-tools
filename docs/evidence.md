# Sources and citations

`sources(transcript)` returns the pages found in hosted search results, once per URL
in first-appearance order. `citations(transcript)` returns citations attached to
assistant text in transcript order. A searched page may never be cited.

The same readers work on a transcript from a live agent run. This short example
constructs the relevant transcript parts so their different results are easy to see:

```python
from agentloop import Citation, HostedToolPart, Source, Transcript
from agentloop.transcript import TextPart
from agentloop_tools.web import citations, sources

transcript = Transcript()
transcript.add_user_message("Summarize the source.")
transcript.add_assistant_message([
    HostedToolPart(
        kind="web_search",
        sources=(
            Source(url="https://example.org/a"),
            Source(url="https://example.org/b"),
            Source(url="https://example.org/a"),
        ),
    ),
    TextPart(
        text="A short summary.",
        citations=(Citation(url="https://example.org/b"),),
    ),
])

print([source.url for source in sources(transcript)])
print([citation.url for citation in citations(transcript)])
```

Output:

```text
['https://example.org/a', 'https://example.org/b']
['https://example.org/b']
```

`sources()` reads hosted tool parts. `citations()` reads citation data on assistant
content. Both return empty lists when that evidence is absent. Anthropic dynamic
filtering may produce sources without citations because the model sees the filtering
program's output instead of citation-bearing search results.
