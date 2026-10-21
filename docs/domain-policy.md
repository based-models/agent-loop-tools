# Domain policies

`DomainPolicy` keeps one allowlist or blocklist for two steps. First,
`policy.native_web_search()` sends its domains to the provider's search tool. After
the response, `policy.audit(transcript)` reports any disallowed domains found in
assistant search sources, citations, or answer text.

## Create and use a policy

```python
from agentloop_tools.web import DomainPolicy

policy = DomainPolicy.allow(["python.org"])
search = policy.native_web_search()

print(search.options)
print(policy.permits("https://docs.python.org/3/"))
print(policy.permits("https://example.org/"))
```

Output:

```text
{'allowed_domains': ['python.org']}
True
False
```

Use `search` in an `Agent`'s `tools` list, as in the
[native search guide](native-web-search.md). For a blocklist, call
`DomainPolicy.block(["example.org"])`; other domains remain permitted.
`policy.match(url)` returns the rule that matched or `None`. A host rule includes
subdomains, and an optional path limits the rule to that path prefix. Passing
domain options to `policy.native_web_search()` raises `ValueError` because the
policy already supplies them.

## Audit an answer

```python
from agentloop import Transcript
from agentloop.transcript import TextPart
from agentloop_tools.web import DomainPolicy

policy = DomainPolicy.allow(["python.org"])
transcript = Transcript()
transcript.add_user_message("Summarize the topic.")
before = len(transcript.messages)
transcript.add_assistant_message([
    TextPart(text="See https://example.org/guide for details."),
])

for violation in policy.audit(transcript, since=before):
    print(violation.where, violation.url, violation.rule)
```

Output:

```text
text https://example.org/guide None
```

`since` is the transcript message index to start scanning, useful when auditing
only the latest turn. Each `Violation` has `where`, `url`, `message_index`, and
`rule` fields. `rule` is the matching blocklist entry in block mode and `None`
for a URL outside an allowlist. An allowlist audit checks full URLs in answer
text; a blocklist audit also checks bare mentions of blocked hosts.

The audit reads the transcript and returns violations. Your application decides
how to handle them. Because the provider performs native search inside its own
response, the audit cannot stop the model from reading a page returned by the
provider. See [sources and citations](evidence.md) for the evidence it inspects.
