# Architecture

- `wenling_core`: embedded rules, scoring, tile efficiency, state machine, validation, and protocol version.
- `wenling_lan_host`: authoritative BattleSession, private account views, SQLite account state, and LAN HTTP host.
- `static`: responsive browser battle client.
- `config/default.json`: versioned host, port, data, and static defaults.

The server owns all hidden information and legal-action validation. Browser and future WebView clients receive only account-filtered state.

No Cloudflare, Torch, DMC, or training module is present.
