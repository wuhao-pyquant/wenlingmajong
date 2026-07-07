# Handoff

## Current

- Runnable PC LAN host on `0.0.0.0`.
- Browser login, seating, ready state, full authoritative game, private views, reconnect, stats, and reports.
- Bearer-token browser sessions with owner-created enabled accounts.
- Offline account create/disable/restore/delete/clear/merge with rotating backups.
- Android Compose owner console and Chaquopy foreground host-service project.
- Versioned health and host-information endpoints.
- Configurable data and static directories.

## Reserved Boundaries

- Persistent active-hand restoration.
- Password/PIN account authentication.
- Android 17 target-SDK local-network permission rollout.
- Optional mDNS discovery; v1 uses explicit URLs and QR codes.

## Limits

- Android platform 36, lint, Kotlin compilation, and the arm64 `phoneDebug`
  package have been verified. Physical local-only-hotspot behavior still needs
  validation on the target phone because emulators cannot represent vendor
  SoftAP and battery-management behavior accurately.
- Browser session tokens are intentionally in-memory and expire when the room stops.
- Manual testing from another physical LAN device remains required.
