# Changelog

All notable changes to HomeHoard are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/);
versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.2.0] – 2026-07-02

### Changed
- **Rebrand: Shelfie → HomeHoard.** Renamed across the board — GitHub repo,
  GHCR image (`ghcr.io/amantux/homehoard`), Home Assistant add-on slug, HACS
  integration domain (`custom_components/homehoard`), UI, and docs. The `HBOX_`
  environment-variable prefix is retained as an internal detail. Reinstall the
  HA add-on and integration under the new name; the database starts fresh.

---

## [0.1.1] – 2026-07-02

### Fixed
- **Home Assistant add-on install failed with `manifest unknown` (404).** The
  add-on pins `image: ghcr.io/amantux/homehoard` at the version in `config.yaml`,
  but no matching image tag had been published (only `latest` + commit SHAs).
  CI now publishes a version-tagged multi-arch image so the pinned version
  always resolves.

### Added
- **Versioning & release automation.** CI auto-bumps the patch version in both
  `homehoard/config.yaml` and `custom_components/homehoard/manifest.json` on every
  push to `main`, keeping the add-on and integration versions in lockstep, then
  publishes `ghcr.io/amantux/homehoard:<version>` and `:latest`
  (linux/amd64 + linux/arm64 for Raspberry Pi 5).
- **Functional changelogs.** A root changelog (this file) plus a per-add-on
  `homehoard/CHANGELOG.md` that Home Assistant surfaces in the add-on store.
- CI `validate-addon` job asserts the add-on and integration versions match.

---

## [0.1.0] – 2026-07-02

### Added
- Initial public release: a personal rewrite of
  [homebox](https://github.com/hay-kot/homebox) in **Flask + SQLAlchemy** with a
  **Vue 3** SPA.
- **Bins** (location → bin → items); moving a bin moves its items with it.
- **QR codes & barcodes**: printable HomeHoard QR labels, plus register your own
  QR/UPC/EAN codes and scan them (native `BarcodeDetector` with a ZXing fallback
  for iOS/Safari).
- **Home Assistant**: Supervisor add-on (Ingress + discovery) and a HACS
  integration exposing inventory sensors.
- CSV import/export compatible with homebox's `HB.*` columns.
- Optional auth (disabled by default behind Ingress).

[0.1.1]: https://github.com/Amantux/homehoard/releases/tag/0.1.1
[0.1.0]: https://github.com/Amantux/homehoard/releases/tag/0.1.0
