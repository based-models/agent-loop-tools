# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/). Versioning: SemVer; while `0.x`, a
minor release may change the public API.

## [0.2.0]

### Changed
- Requires `based-models-agentloop>=0.5.0,<0.6.0` (was `>=0.4.0,<0.5.0`), so it installs
  alongside the current agentloop. The 44 tests pass against agentloop 0.5.0.

## [0.1.0]

### Added
- `native_web_search`, `DomainPolicy`, `sources()` and `citations()` for agentloop's hosted
  web search, published on PyPI as `based-models-agentloop-tools` (Apache-2.0).
