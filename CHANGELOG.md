# Changelog

## 0.1.0 (2026-10-01)


### Features

* add hook system ([304a1f3](https://github.com/KristopherKubicki/norman/commit/304a1f369f24bc26b81b5bd4b46a7f491126431c))
* **connector:** implement matrix listener ([610ba2c](https://github.com/KristopherKubicki/norman/commit/610ba2c50b514caa191bce5d25e2019997a04a79))
* **connector:** verify Intercom token ([951c2e8](https://github.com/KristopherKubicki/norman/commit/951c2e8cf8900a2f11095f536ff2e9217876a8c9))
* enable compression and caching ([99be10c](https://github.com/KristopherKubicki/norman/commit/99be10cfbf938b8851fc9059ecf6df468d4bf2ae))
* enable event webhooks ([275e10e](https://github.com/KristopherKubicki/norman/commit/275e10e18c03dcfa1fe6e492834b285f023f7137))
* implement snapchat connector ([b5ec922](https://github.com/KristopherKubicki/norman/commit/b5ec922a2439a1e2433e03d8cc1c53fec3def0f9))
* integrate durable Bridge conversations and mobile login experience ([85e9e30](https://github.com/KristopherKubicki/norman/commit/85e9e305d5e9d8f0e1cdb148ecc1e6b8cb46b38e))
* release v0.2.0 ([e94648e](https://github.com/KristopherKubicki/norman/commit/e94648ec8d05e6caec85a1974c7668a082152d96))
* **ui:** add shimmering placeholder while messages load ([e4959d4](https://github.com/KristopherKubicki/norman/commit/e4959d4b5afac1d26ba0f18c9a627b593bcda91d))
* **ui:** highlight active navigation ([c7b9b81](https://github.com/KristopherKubicki/norman/commit/c7b9b814537ef13d63e13d0d4cf5629ec23f5f2c))
* **ui:** persist theme and respect system preference ([c3b05c7](https://github.com/KristopherKubicki/norman/commit/c3b05c7a86c0c86516c30735e114d9fc26dc3438))


### Bug Fixes

* align integrated console versions and staging compatibility checks ([39a953b](https://github.com/KristopherKubicki/norman/commit/39a953be81e010a5513d7a2dd6de40b0464ab1dc))
* authenticate browser sign-in callbacks before handoff ([67a1b5b](https://github.com/KristopherKubicki/norman/commit/67a1b5be3354d1246ebf63e3b78df1b86a706633))
* authenticate browser sign-in callbacks before handoff ([e2d7c19](https://github.com/KristopherKubicki/norman/commit/e2d7c1995d5f2ba1606f10de758ff8e9b6e057d3))
* classify estate routes by parsed hostname ([bb49b22](https://github.com/KristopherKubicki/norman/commit/bb49b22a962600ea04940577adf48f1eef5efb60))
* clear frontend dependency advisories and isolate relay tests ([61049e9](https://github.com/KristopherKubicki/norman/commit/61049e9907117cfc5384b03a62308ef7efb5153b))
* preserve console drafts and give reliable delivery and mobile feedback ([3ed7bd4](https://github.com/KristopherKubicki/norman/commit/3ed7bd4f724928a6c6f2f75b8c004a6cc00228ff))
* remove duplicate import ([22e1bcf](https://github.com/KristopherKubicki/norman/commit/22e1bcfa13d5011ff1aef73f65909c0bee588b74))
* require patched PyJWT and pytest releases ([757286d](https://github.com/KristopherKubicki/norman/commit/757286d0adc2849b93453e06cbb2e75450893ef5))
* require patched PyJWT and pytest releases ([d5e7c39](https://github.com/KristopherKubicki/norman/commit/d5e7c3975def7d9b645c2440e286d8328b5dfdde))
* update vulnerable frontend development dependencies ([2821876](https://github.com/KristopherKubicki/norman/commit/2821876b212aa1006751884eb6c5f1145d840a20))


### Documentation

* add OpenSSF Scorecard badge ([ce54a20](https://github.com/KristopherKubicki/norman/commit/ce54a20b4a0c679bf19f95e1681d74ebc7ab1446))
* add python 3.10 support ([92872d2](https://github.com/KristopherKubicki/norman/commit/92872d29b47bb70ece43cc53fc680c3b041003be))
* add style guide and lint tooling ([2c4d21c](https://github.com/KristopherKubicki/norman/commit/2c4d21c8995c7ee70cb82313dacec4d10d72ff5c))
* add Zoom connector ([42b3ecc](https://github.com/KristopherKubicki/norman/commit/42b3ecca81b45526e1b9b0011c42c1e939efb449))
* clarify first run steps ([07a04ab](https://github.com/KristopherKubicki/norman/commit/07a04abb76934dc867de7e9d7c71b8d8a3b8b1d2))
* document connectors info endpoint ([feeb760](https://github.com/KristopherKubicki/norman/commit/feeb7608eec3bb7dc8c5191cb3a080e77111d5f2))
* finalize todo lists ([b14e75a](https://github.com/KristopherKubicki/norman/commit/b14e75a7d0dd9148484d3f52b7a67148bbf9bc9a))
* Fix rate limiting heading ([7b1fb72](https://github.com/KristopherKubicki/norman/commit/7b1fb72fff7f59c8f10f4ab760a1268abb02d28f))
* wrap lines within 120 chars ([5e0021c](https://github.com/KristopherKubicki/norman/commit/5e0021c6ef1acb56e64dab37f64aa7bcd913268d))

## [Unreleased]

### Changed

- Reframed the README and core documentation around Norman as a local-first
  operator control plane for durable, policy-governed AI-assisted work.
- Documented provider-neutral routing: deterministic tools and Norllama local
  capabilities are preferred; cloud providers are explicit, policy-gated
  routes with receipts.
- Published the Console Runtime, human-approval, Kaizen/KPI, degraded-mode,
  Codex gateway, SMS/BBS, and host-pressure operating guidance.
- Recorded the approved, contract-first Norllama repository extraction plan.
  Norllama remains in this repository until its versioned contracts, dual-run,
  cutover, and rollback gates are complete.

## [0.2.0] - 2025-06-03

### Added

- Zoom chat connector and support for additional platforms
- Real-time thinking indicator during message processing
- Connector status monitoring UI with responsive design improvements
- Form input validation and authentication enforcement for admin UI
- Pre- and post-processing hooks and enhanced logging
- Docker deployment configuration

## [0.1.0] - 2025-06-02

### Added

- Initial release of Norman chatbot with GPT integration, connectors, and minimal web UI.
