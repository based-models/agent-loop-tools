from typing import Any

import pytest
from agentloop import Citation, HostedToolPart, Source, Transcript
from agentloop.provider import ModelRequest
from agentloop.providers._openai_compat import Quirks
from agentloop.providers._openai_responses import request_to_wire as responses_wire
from agentloop.providers.anthropic import request_to_wire as anthropic_wire
from agentloop.transcript import TextPart

from agentloop_tools.web import DomainPolicy, Violation

BLOCK = DomainPolicy.block(["wikipedia.org", "example.com/private"])
ALLOW = DomainPolicy.allow(["europa.eu", "python.org"])


# --- construction ---


def test_a_policy_is_one_mode_with_normalized_domains() -> None:
    policy = DomainPolicy.block([" Wikipedia.ORG "])
    assert (policy.mode, policy.domains) == ("block", ("wikipedia.org",))


def test_an_empty_policy_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one domain"):
        DomainPolicy.allow([])


def test_bad_domains_are_refused_as_elsewhere() -> None:
    with pytest.raises(ValueError, match="without a scheme"):
        DomainPolicy.block(["https://wikipedia.org"])
    with pytest.raises(ValueError, match="not ASCII"):
        DomainPolicy.block(["wikipedіa.org"])   # Cyrillic і


# --- matching: the providers' rules ---


@pytest.mark.parametrize(
    ("target", "rule"),
    [
        ("wikipedia.org", "wikipedia.org"),
        ("https://en.wikipedia.org/wiki/Python", "wikipedia.org"),     # subdomain
        ("HTTPS://EN.WIKIPEDIA.ORG/x", "wikipedia.org"),                # case
        ("https://www.wikipedia.org:443/", "wikipedia.org"),            # www. and port
        ("wikipedia.org.", "wikipedia.org"),                            # trailing dot
        ("https://example.com/private/report", "example.com/private"),  # path prefix
        ("https://notwikipedia.org/x", None),                           # longer label
        ("https://wikipedia.org.evil.test/", None),                     # not a suffix
        ("https://example.com/public", None),                           # other path
    ],
)
def test_match_follows_host_subdomain_and_path_rules(target: str, rule: str | None) -> None:
    assert BLOCK.match(target) == rule


def test_a_wildcard_matches_within_the_path() -> None:
    policy = DomainPolicy.block(["example.com/*/drafts"])
    assert policy.match("https://example.com/team/drafts/1") == "example.com/*/drafts"
    assert policy.match("https://example.com/team/final") is None


def test_permits_is_inverted_between_modes() -> None:
    assert not BLOCK.permits("https://en.wikipedia.org/x")
    assert BLOCK.permits("https://python.org")
    assert ALLOW.permits("https://eur-lex.europa.eu/x")     # on-list subdomain
    assert not ALLOW.permits("https://wikipedia.org")


# --- prevent: the provider receives the policy's list ---


def wire_tools(policy: DomainPolicy) -> tuple[dict[str, Any], dict[str, Any]]:
    request = ModelRequest(messages=(), hosted_tools=(policy.native_web_search(max_uses=2),))
    [anthropic] = anthropic_wire(request, model="claude-opus-5")["tools"]
    [openai] = responses_wire(request, model="gpt-x", quirks=Quirks())["tools"]
    return anthropic, openai


def test_a_blocklist_is_sent_to_both_providers() -> None:
    anthropic, openai = wire_tools(BLOCK)
    assert anthropic["blocked_domains"] == ["wikipedia.org", "example.com/private"]
    assert openai["filters"] == {"blocked_domains": ["wikipedia.org", "example.com/private"]}
    assert anthropic["max_uses"] == 2                        # other options pass through


def test_an_allowlist_is_sent_to_both_providers() -> None:
    anthropic, openai = wire_tools(ALLOW)
    assert anthropic["allowed_domains"] == ["europa.eu", "python.org"]
    assert openai["filters"] == {"allowed_domains": ["europa.eu", "python.org"]}


def test_the_policy_is_the_only_source_of_domains() -> None:
    with pytest.raises(ValueError, match="already sets the domains"):
        BLOCK.native_web_search(allowed_domains=["python.org"])


# --- report: sources, citations, text ---


def turn(*parts: Any) -> Transcript:
    transcript = Transcript()
    transcript.add_user_message("See wikipedia.org and https://en.wikipedia.org/wiki/X")
    transcript.add_assistant_message(list(parts))
    return transcript


def search(*urls: str) -> HostedToolPart:
    return HostedToolPart(kind="web_search", sources=tuple(Source(url=u) for u in urls))


def test_a_clean_turn_has_no_violations() -> None:
    clean = turn(search("https://python.org/downloads"),
                 TextPart(text="See https://docs.python.org/3/.",
                          citations=(Citation(url="https://python.org/x"),)))
    assert BLOCK.audit(clean) == []


def test_each_kind_of_leak_is_reported_where_it_happened() -> None:
    transcript = turn(
        search("https://python.org", "https://en.wikipedia.org/wiki/Python"),
        TextPart(text="Released in 1991.",
                 citations=(Citation(url="https://en.wikipedia.org/wiki/Python"),)),
        TextPart(text="Per [Wikipedia](https://en.wikipedia.org/wiki/Python), "
                      "also at wikipedia.org."),
    )
    assert BLOCK.audit(transcript) == [
        Violation("https://en.wikipedia.org/wiki/Python", "source", 1, "wikipedia.org"),
        Violation("https://en.wikipedia.org/wiki/Python", "citation", 1, "wikipedia.org"),
        Violation("https://en.wikipedia.org/wiki/Python", "text", 1, "wikipedia.org"),
        Violation("wikipedia.org", "text", 1, "wikipedia.org"),   # bare mention
    ]


@pytest.mark.parametrize(
    "text",
    [
        "See https://en.wikipedia.org/wiki/Python_(programming_language).",
        "See [Python](https://en.wikipedia.org/wiki/Python_(programming_language)).",
        "(https://en.wikipedia.org/wiki/Python_(programming_language))",
    ],
)
def test_a_url_keeps_its_own_parentheses(text: str) -> None:
    """Seen live: the Wikipedia URL was cut at "(" to ".../Python_"."""
    [violation] = BLOCK.audit(turn(TextPart(text=text)))
    assert violation.url == "https://en.wikipedia.org/wiki/Python_(programming_language)"


def test_the_prose_source_list_seen_live_is_caught() -> None:
    """With dynamic filtering the model lists its sources in prose instead of citing."""
    prose = ("\n\nSources: [IEEE Information Theory Society](https://www.itsoc.org/about/shannon),"
             " [Wikipedia](https://en.wikipedia.org/wiki/Claude_Shannon).")
    [violation] = BLOCK.audit(turn(TextPart(text=prose)))
    assert violation.url == "https://en.wikipedia.org/wiki/Claude_Shannon"   # no ")" or "."


def test_a_mention_is_not_mistaken_for_a_longer_domain() -> None:
    text = "Unrelated: notwikipedia.org, wikipedia.org.uk, my-wikipedia.org-fan."
    assert BLOCK.audit(turn(TextPart(text=text))) == []


def test_user_messages_are_never_flagged() -> None:
    assert BLOCK.audit(turn(TextPart(text="Nothing to see."))) == []


def test_since_limits_the_audit_to_new_messages() -> None:
    transcript = turn(TextPart(text="Old: wikipedia.org"))
    before = len(transcript.messages)
    transcript.add_user_message("again")
    transcript.add_assistant_message([TextPart(text="New: https://en.wikipedia.org/x")])
    [violation] = BLOCK.audit(transcript, since=before)
    assert violation.message_index == 3


def test_allow_mode_flags_off_list_urls_with_no_rule() -> None:
    transcript = turn(
        search("https://eur-lex.europa.eu/doc", "https://blog.example.net/post"),
        TextPart(text="From https://reddit.com/r/x and config.py, see europa.eu.",
                 citations=(Citation(url="https://python.org/downloads"),)),
    )
    assert ALLOW.audit(transcript) == [
        Violation("https://blog.example.net/post", "source", 1, None),
        Violation("https://reddit.com/r/x", "text", 1, None),
    ]   # bare words ("config.py", "europa.eu") are not scanned in allow mode


def test_audit_does_not_modify_the_transcript() -> None:
    transcript = turn(search("https://en.wikipedia.org/x"), TextPart(text="wikipedia.org"))
    snapshot = transcript.model_copy(deep=True)
    BLOCK.audit(transcript)
    assert transcript == snapshot
