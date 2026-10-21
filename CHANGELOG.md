# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/). Versioning: SemVer; while `0.x`, a
minor release may change the public API.

## [0.1.2]

### Changed
- Allow `based-models-agentloop` 0.6 (`>=0.4.0,<0.7.0`, was `<0.6.0`). The test suite, ruff and
  mypy pass unchanged against agentloop 0.6.0 installed from PyPI.
- README documentation links point at the published docs on basedmodels.com.

## [0.1.1]

### Changed
- Allow `based-models-agentloop` 0.5 (`>=0.4.0,<0.6.0`, was `<0.5.0`). The test suite, ruff and
  mypy pass unchanged against both 0.4.0 and 0.5.0; this package uses none of the API that
  0.5.0 changed.

## [0.1.0]

### Added
- `native_web_search`, `DomainPolicy`, `sources()` and `citations()` for agentloop's hosted
  web search, published on PyPI as `based-models-agentloop-tools` (Apache-2.0).
