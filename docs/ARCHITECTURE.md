# Architecture

- `wenling_core`: embedded rules, scoring, tile efficiency, state machine, validation, and protocol version.
- `wenling_lan_host`: authoritative BattleSession, private account views, SQLite account state, and LAN HTTP host.
- `static`: responsive browser battle client.
- `android-host`: Kotlin/Compose owner console, Chaquopy Python runtime, foreground room service, address/QR display, and process-local administration bridge.
- `config/default.json`: versioned host, port, data, and static defaults.

The server owns all hidden information and legal-action validation. Browser and future WebView clients receive only account-filtered state.

LAN players may self-register a username of up to 12 characters or select an
enabled account, then receive an opaque bearer token. Account names in request
bodies and query strings do not select the private view. A new login revokes the
previous token for that account.

Owner operations are not HTTP APIs on Android. Compose calls `wenling_lan_host.android_bridge` in-process. Room writes still use the BattleSession FIFO event queue and room-generation checks. Account and history mutation is rejected while the room server is running.

There is no browser-side owner account role. Owner authority is established by
the Android in-process bridge or a PC loopback-only request. Ordinary seated
players may request random reseating after settlement, while forced seat,
account, and historical-statistics management remain owner-only.

Single-hand luck is scored at settlement by the embedded standard-library-only runtime under `wenling_core/hand_luck_runtime`. The jump-bool model consumes seat, de draws, scoring-flower draws, opening/final normal shanten, normal draw count, open claim count, opening/final leizi distance, supplement draw count, and explicit jump events derived from the winner's `win_type` (`劣子和`, `自摸得`, `杠上开花`, `rob_gang`/`抢杠胡`/`抢杠和`). Its 0-100 percentile is attached to settlement state. SQLite stores historical score totals/counts, while `BattleSession` separately holds the current room average in memory so it resets only when the room host is fully closed.

No Cloudflare, Torch, DMC, or training module is present. Active hands are intentionally not restored after Android process death.
