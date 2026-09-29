from typing import Any

import pytest
from agentloop import (
    Agent,
    Citation,
    HostedTool,
    HostedToolPart,
    Source,
    Transcript,
)
from agentloop.provider import ModelRequest, ModelResponse, StopReason, Usage
from agentloop.providers._openai_compat import Quirks
from agentloop.providers._openai_responses import request_to_wire as responses_wire
from agentloop.providers.anthropic import request_to_wire as anthropic_wire
from agentloop.transcript import TextPart

from agentloop_tools.web import WEB_SEARCH, citations, native_web_search, sources

# --- the factory: typed options, validated before any request ---


def test_the_default_is_a_bare_hosted_web_search() -> None:
    assert native_web_search() == HostedTool(kind=WEB_SEARCH, options={})


def test_only_the_non_default_filtering_setting_travels() -> None:
    assert native_web_search(dynamic_filtering=True).options == {"dynamic_filtering": True}
    assert native_web_search(dynamic_filtering=False).options == {}


def test_anthropic_gets_basic_search_unless_filtering_is_asked_for() -> None:
    """The default here and the adapter's default must agree: basic search, which
    keeps citations. Dynamic filtering returned none in 6 of 6 live requests."""

    def version(tool: HostedTool) -> str:
        request = ModelRequest(messages=(), hosted_tools=(tool,))
        return str(anthropic_wire(request, model="claude-opus-5")["tools"][0]["type"])

    assert version(native_web_search()) == "web_search_20250305"
    assert version(native_web_search(dynamic_filtering=True)) == "web_search_20260209"


def test_domains_are_normalized_and_paths_kept() -> None:
    tool = native_web_search(allowed_domains=[" Europa.EU ", "eur-lex.europa.eu/legal"])
    assert tool.options["allowed_domains"] == ["europa.eu", "eur-lex.europa.eu/legal"]


@pytest.mark.parametrize(
    ("domain", "reason"),
    [
        ("https://europa.eu", "without a scheme"),
        ("аmazon.com", "not ASCII"),                # Cyrillic а: a homograph
        ("*.example.com", "wildcards"),
        ("", "bare domain"),
    ],
)
def test_bad_domains_are_refused(domain: str, reason: str) -> None:
    with pytest.raises(ValueError, match=reason):
        native_web_search(blocked_domains=[domain])


def test_allowed_and_blocked_are_exclusive() -> None:
    with pytest.raises(ValueError, match="not both"):
        native_web_search(allowed_domains=["a.com"], blocked_domains=["b.com"])


def test_limits_and_location_are_checked() -> None:
    with pytest.raises(ValueError, match="max_uses"):
        native_web_search(max_uses=0)
    with pytest.raises(ValueError, match="two letters"):
        native_web_search(user_location={"country": "Belgium"})
    with pytest.raises(ValueError, match="search_context_size"):
        native_web_search(search_context_size="huge")  # type: ignore[arg-type]


# --- what each provider receives ---


def test_both_providers_receive_the_same_restriction() -> None:
    tool = native_web_search(allowed_domains=["europa.eu"], user_location={"country": "BE"})
    request = ModelRequest(messages=(), hosted_tools=(tool,))
    [anthropic] = anthropic_wire(request, model="claude-opus-5")["tools"]
    [openai] = responses_wire(request, model="gpt-x", quirks=Quirks())["tools"]
    assert anthropic["allowed_domains"] == ["europa.eu"]
    assert openai["filters"] == {"allowed_domains": ["europa.eu"]}
    assert anthropic["user_location"] == openai["user_location"] == {
        "type": "approximate", "country": "BE",
    }


# --- through an Agent ---


class SearchingClient:
    name, model = "fake", "m"
    hosted_tools = frozenset({"web_search"})

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(
            content=(
                HostedToolPart(kind="web_search", query="q",
                               sources=(Source(url="https://europa.eu/x", title="EU"),)),
                TextPart(text="Answer.", citations=(Citation(url="https://europa.eu/x"),)),
            ),
            stop_reason=StopReason.END_TURN, usage=Usage(), model="m", provider="fake",
        )


def test_an_agent_declares_it_on_every_request_and_the_readers_find_the_evidence() -> None:
    client = SearchingClient()
    agent = Agent([native_web_search(max_uses=2)], client=client)
    transcript = Transcript()
    transcript.add_user_message("What changed?")
    agent.converse(transcript)
    assert client.requests[0].hosted_tools[0].options == {"max_uses": 2}
    assert [s.url for s in sources(transcript)] == ["https://europa.eu/x"]
    assert [c.url for c in citations(transcript)] == ["https://europa.eu/x"]


def test_sources_are_deduplicated_in_order() -> None:
    def search(*urls: str) -> Any:
        return HostedToolPart(kind="web_search", sources=tuple(Source(url=u) for u in urls))

    transcript = Transcript()
    transcript.add_user_message("go")
    transcript.add_assistant_message([search("https://a", "https://b"), search("https://a")])
    assert [s.url for s in sources(transcript)] == ["https://a", "https://b"]
