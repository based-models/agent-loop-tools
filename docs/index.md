# agentloop-tools documentation

`agentloop-tools` adds typed tool helpers to `agentloop`. Its current tool family
configures provider-hosted web search and reads the evidence recorded in a transcript.
The provider runs the search. `agentloop` sends the tool configuration and records the
response; `agentloop-tools` validates options and helps inspect the result.

Start with the [README](../README.md) for installation and a complete agent example.
Then use these guides:

- [Native web search](native-web-search.md) explains the tool factory, provider support,
  and search options.
- [Sources and citations](evidence.md) shows how to read search evidence from a
  `Transcript`.
- [Domain policies](domain-policy.md) explains allowlists, blocklists, and auditing.

Import this tool family from `agentloop_tools.web`. The package root does not re-export
its functions or classes.
