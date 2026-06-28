# Operations

Start with `start_lan.ps1` or the module command. Stop with `Ctrl+C`.

The default database is new and lives at `data/battle.sqlite3`. Back up the entire `data` directory while the host is stopped. Listening on `0.0.0.0` makes the service reachable on all local interfaces; use a trusted LAN and a firewall rule limited to the private network profile.

Check `/api/health` and `/api/host/info` when diagnosing connectivity. Verify the client uses the PC LAN IP, not `127.0.0.1`.
