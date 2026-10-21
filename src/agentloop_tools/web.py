"""Web tools.

Today: NATIVE web search, which the provider runs (Anthropic's server tool,
OpenAI's Responses `web_search`). `native_web_search` returns an agentloop
`HostedTool`: typed and validated here, translated by agentloop's adapters, and
refused at `Agent` construction by a provider that cannot run it.

Client-side search -- your own code calling a search API -- is a separate,
first-class choice, not a fallback for this one. It is planned for a later release.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict
from urllib.parse import urlsplit

from agentloop import Citation, HostedTool, HostedToolPart, Source, Transcript

WEB_SEARCH = "web_search"

type ContextSize = Literal["low", "medium", "high"]


class UserLocation(TypedDict, total=False):
    """Approximate location, to localize results. Both providers take these."""

    city: str
    region: str
    country: str  # ISO 3166-1 alpha-2, e.g. "BE"
    timezone: str  # IANA, e.g. "Europe/Brussels"


def native_web_search(
    *,
    allowed_domains: Iterable[str] = (),
    blocked_domains: Iterable[str] = (),
    max_uses: int | None = None,
    user_location: UserLocation | None = None,
    dynamic_filtering: bool = False,
    search_context_size: ContextSize | None = None,
) -> HostedTool:
    """Web search run by the provider. Pass the result in an Agent's tools.

    - `allowed_domains` / `blocked_domains`: one or the other. Bare domains,
      optionally with a path (`europa.eu/legal`); subdomains are included.
      ASCII only: a look-alike Unicode domain would slip past the filter.
    - `max_uses`: a cap on searches per request (Anthropic; OpenAI ignores it
      with a warning).
    - `dynamic_filtering`: Anthropic only, off by default. On, Claude (4.6+)
      runs code that filters results before they reach its context, which can
      save tokens on search-heavy requests -- but the model then reads the
      program's output, not the results, so `citations()` comes back EMPTY.
      `sources()` still works. Not ZDR-eligible. OpenAI ignores it with a warning.
    - `search_context_size`: how much page content OpenAI feeds the model
      (Anthropic ignores it with a warning).

    Evidence: read `sources(transcript)` for the pages searched -- every mode
    fills it -- and `citations(transcript)` for claims tied to a page, which only
    basic search (the default) and OpenAI produce.
    """
    allowed = _domains(allowed_domains, "allowed_domains")
    blocked = _domains(blocked_domains, "blocked_domains")
    if allowed and blocked:
        raise ValueError("pass allowed_domains or blocked_domains, not both")
    if max_uses is not None and max_uses < 1:
        raise ValueError(f"max_uses must be at least 1, got {max_uses}")
    if search_context_size not in (None, "low", "medium", "high"):
        raise ValueError(f"search_context_size must be low, medium or high, "
                         f"got {search_context_size!r}")

    options: dict[str, Any] = {}
    if allowed:
        options["allowed_domains"] = allowed
    if blocked:
        options["blocked_domains"] = blocked
    if max_uses is not None:
        options["max_uses"] = max_uses
    if user_location:
        options["user_location"] = _location(user_location)
    if dynamic_filtering:
        options["dynamic_filtering"] = True  # only the non-default travels
    if search_context_size is not None:
        options["search_context_size"] = search_context_size
    return HostedTool(kind=WEB_SEARCH, options=options)


def sources(transcript: Transcript) -> list[Source]:
    """Every page a hosted search consulted, first appearance first, no repeats."""
    seen: dict[str, Source] = {}
    for message in transcript.messages:
        for part in message.content:
            if isinstance(part, HostedToolPart):
                for source in part.sources:
                    seen.setdefault(source.url, source)
    return list(seen.values())


def citations(transcript: Transcript) -> list[Citation]:
    """Every citation the model attached to its text, in order."""
    return [
        citation
        for message in transcript.messages
        if message.role == "assistant"
        for part in message.content
        for citation in getattr(part, "citations", ())
    ]


# --- domain policy: prevent at the provider, report what came out -----------

type PolicyMode = Literal["block", "allow"]
type Where = Literal["source", "citation", "text"]

# A full URL in prose or a markdown link target. Balanced parentheses stay in
# the URL -- Wikipedia's ".../Python_(programming_language)", seen live -- while
# an unbalanced ")" ends it, so "[x](https://a.b/c)" still yields "https://a.b/c".
_URL = re.compile(
    r"https?://(?:[^\s<>()\[\]\"'`]|\([^\s<>()\[\]\"'`]*\))+", re.IGNORECASE
)
_TRAILING = ".,;:!?"


@dataclass(frozen=True)
class Violation:
    """One place a finished turn reached a domain the policy does not permit.

    `rule` is the blocklist entry that matched, or None for "not on the allowlist".
    What to do about it -- log, raise, re-ask, warn the user -- is the caller's call.
    """

    url: str
    where: Where
    message_index: int
    rule: str | None


@dataclass(frozen=True)
class _Rule:
    text: str
    host: str
    path: re.Pattern[str] | None
    mention: re.Pattern[str]  # the rule written in prose, host (+ path) only


@dataclass(frozen=True)
class DomainPolicy:
    """A blocklist or an allowlist for native web search: prevent, then report.

    Build one with `DomainPolicy.block([...])` or `DomainPolicy.allow([...])` --
    one or the other, as both providers require.

    PREVENT: `policy.native_web_search(...)` sends the list to the provider, which
    filters the search itself. REPORT: `policy.audit(transcript)` lists every
    place a finished turn still reached a domain the policy does not permit.

    The limit: with native search the provider runs the search and the model reads
    the results inside one response, so nothing here can stop the model READING a
    page. It prevents what the provider can prevent and reports the rest. Matching
    follows the providers' rules: a rule covers its host and every subdomain, but
    not a longer label (`europa.eu` covers `eur-lex.europa.eu`, not
    `noteuropa.eu`), plus an optional path prefix (`example.com/docs`, where `*`
    matches within the path).
    """

    mode: PolicyMode
    domains: tuple[str, ...]
    _rules: tuple[_Rule, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.domains:
            raise ValueError(f"a {self.mode} policy needs at least one domain")
        object.__setattr__(self, "_rules", tuple(_rule(d) for d in self.domains))

    @classmethod
    def block(cls, domains: Iterable[str]) -> DomainPolicy:
        """Permit everything except these domains (and their subdomains)."""
        return cls("block", tuple(_domains(domains, "blocked_domains")))

    @classmethod
    def allow(cls, domains: Iterable[str]) -> DomainPolicy:
        """Permit only these domains (and their subdomains)."""
        return cls("allow", tuple(_domains(domains, "allowed_domains")))

    # --- prevent ---

    def native_web_search(self, **options: Any) -> HostedTool:
        """`native_web_search(...)` with this policy's list sent to the provider.

        The policy is the one source of truth for domains, so passing
        `allowed_domains` or `blocked_domains` here as well is an error.
        """
        clashes = {"allowed_domains", "blocked_domains"} & set(options)
        if clashes:
            raise ValueError(
                f"{sorted(clashes)}: the policy already sets the domains; pass other "
                "options only"
            )
        if self.mode == "block":
            return native_web_search(blocked_domains=self.domains, **options)
        return native_web_search(allowed_domains=self.domains, **options)

    # --- matching ---

    def match(self, url_or_host: str) -> str | None:
        """The rule `url_or_host` falls under, or None."""
        host, path = _host_and_path(url_or_host)
        for rule in self._rules:
            covered = host == rule.host or host.endswith("." + rule.host)
            if covered and (rule.path is None or rule.path.match(path)):
                return rule.text
        return None

    def permits(self, url_or_host: str) -> bool:
        matched = self.match(url_or_host) is not None
        return not matched if self.mode == "block" else matched

    # --- report ---

    def audit(self, transcript: Transcript, *, since: int = 0) -> list[Violation]:
        """Every place an assistant turn reached a domain this policy does not permit.

        Scans assistant messages from index `since` -- to audit one turn, pass the
        transcript's length from before `converse` -- in transcript order, one record
        per occurrence:

        - "source": a page a hosted search returned (the provider filter leaked);
        - "citation": a page the model cited;
        - "text": a URL written in the answer (including markdown links), and in
          block mode also a bare mention of a blocked host ("see wikipedia.org").
          Allow mode checks full URLs only: finding every host-like word in prose
          would also match file names like `config.py`.

        User messages are never flagged. The transcript is not modified.
        """
        found: list[Violation] = []
        for index, message in enumerate(transcript.messages):
            if index < since or message.role != "assistant":
                continue
            for part in message.content:
                if isinstance(part, HostedToolPart):
                    for source in part.sources:
                        self._check(source.url, "source", index, found)
                for citation in getattr(part, "citations", ()):
                    self._check(citation.url, "citation", index, found)
                text = getattr(part, "text", None)
                if getattr(part, "type", None) == "text" and isinstance(text, str):
                    self._scan_text(text, index, found)
        return found

    def _check(self, url: str, where: Where, index: int, found: list[Violation]) -> None:
        if not self.permits(url):
            found.append(Violation(url, where, index, self.match(url)))

    def _scan_text(self, text: str, index: int, found: list[Violation]) -> None:
        spans: list[tuple[int, int]] = []
        for hit in _URL.finditer(text):
            url = hit.group(0).rstrip(_TRAILING)
            spans.append((hit.start(), hit.start() + len(url)))
            self._check(url, "text", index, found)
        if self.mode == "allow":
            return
        for rule in self._rules:
            for hit in rule.mention.finditer(text):
                if not any(start <= hit.start() < end for start, end in spans):
                    found.append(Violation(hit.group(0), "text", index, rule.text))


def _host_and_path(url_or_host: str) -> tuple[str, str]:
    text = url_or_host.strip()
    parts = urlsplit(text if "://" in text else "//" + text)
    host = (parts.hostname or "").rstrip(".").lower()
    return host.removeprefix("www."), parts.path or "/"


def _rule(domain: str) -> _Rule:
    host, _, path = domain.partition("/")
    host = host.rstrip(".").removeprefix("www.")
    path_re = None
    if path:
        # A path prefix; `*` stands for anything within it.
        path_re = re.compile(re.escape("/" + path).replace(r"\*", ".*"))
    mention = re.compile(
        r"(?<![\w.-])(?:[a-z0-9-]+\.)*" + re.escape(host)
        + (re.escape("/" + path).replace(r"\*", r"\S*") if path else "")
        + r"(?![\w-])(?!\.[a-z0-9])",
        re.IGNORECASE,
    )
    return _Rule(domain, host, path_re, mention)


def _domains(values: Iterable[str], field: str) -> list[str]:
    domains = []
    for raw in values:
        domain = raw.strip().lower()
        host = domain.split("/", 1)[0]
        if not domain or "://" in domain:
            raise ValueError(f"{field}: {raw!r} must be a bare domain, without a scheme")
        if not domain.isascii():
            raise ValueError(f"{field}: {raw!r} is not ASCII (a homograph can bypass filters)")
        if "*" in host or " " in domain:
            raise ValueError(f"{field}: {raw!r} -- wildcards are allowed only in the path")
        domains.append(domain)
    return domains


def _location(location: UserLocation) -> dict[str, str]:
    unknown = set(location) - set(UserLocation.__annotations__)
    if unknown:
        raise ValueError(f"user_location: unknown field(s) {sorted(unknown)}")
    country = location.get("country")
    if country is not None and not (len(country) == 2 and country.isalpha()):
        raise ValueError(f"user_location.country must be two letters, got {country!r}")
    return {key: str(value) for key, value in location.items() if value}
