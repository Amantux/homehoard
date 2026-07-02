# Changelog

## 0.1.1
- **Fix: add-on failed to install (`manifest unknown`, 404).** The add-on is now
  published to GHCR under a version tag that matches `config.yaml`, so Supervisor
  can pull `ghcr.io/amantux/shelfie:<version>`.
- CI now auto-bumps the patch version on every push and publishes a matching
  multi-arch image (amd64 + aarch64 / Raspberry Pi 5).

## 0.1.0
- Initial release of the **Shelfie** Home Assistant add-on.
- Home inventory & organization — a personal rewrite of homebox.
- Ingress UI (no separate login when `disable_auth` is on), QR codes & barcodes,
  and moving-box **bins**.
- Registers Supervisor discovery so the companion HACS integration configures
  itself automatically.
