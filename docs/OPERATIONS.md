# Operations

Start with `start_lan.ps1` or the module command. Stop with `Ctrl+C`.

The default database is new and lives at `data/battle.sqlite3`. Back up the entire `data` directory while the host is stopped. Listening on `0.0.0.0` makes the service reachable on all local interfaces; use a trusted LAN and a firewall rule limited to the private network profile.

Check `/api/health` and `/api/host/info` when diagnosing connectivity. Verify the client uses the PC LAN IP, not `127.0.0.1`.

## Android owner host

1. Keep the room closed while creating, disabling, restoring, deleting, clearing, or merging accounts.
2. Select **手机专用热点** or **外部局域网路由器** while the room is closed.
3. Start the room. Android displays a persistent foreground-service notification.
4. In hotspot mode, let each player scan the Wi-Fi QR code first, keep the
   no-Internet Wi-Fi connected, and then scan the room QR code.
5. In router mode, keep the owner and all players on the same Wi-Fi and share
   the listed `http://<LAN-IP>:8765/battle-login` address.
6. Stop the room from the app or notification when finished. Stopping a hotspot
   room also removes the temporary Wi-Fi network.

The owner may also play from the same phone. Tap **房主在本机浏览器参战**
after starting the room. The browser uses the loopback address, so this works
in both connection modes and does not depend on the displayed LAN address. The
owner's browser account has normal player permissions; return to the Android
app for seat and account administration.

Seat changes and kicks are locked during an active hand. They become available before the game and after `round_over`.

Destructive account operations create timestamped SQLite snapshots under the app-private `runtime/backups` directory. The newest ten backups are retained.

Every completed hand, including a draw, receives four model-based luck percentiles. Players see the current room average, which resets when the host service is fully stopped. The owner database view shows the persisted historical average.

## Android background hosting and latency

While a room is running, the foreground service is declared as both
`connectedDevice` and `dataSync`, holds a partial CPU wake lock, and requests the
platform high-performance Wi-Fi lock. All locks and any local-only hotspot
reservation are released when the owner stops the room. This is required for a
phone-hosted real-time LAN server with the screen off and will increase battery
usage.

When the owner starts a room, the app opens Android's battery-optimization
exemption prompt if the app is not already unrestricted. This should be allowed
on phones used as the room host. The service also runs an internal watchdog: if
the local HTTP health endpoint stops responding while the foreground service is
still alive, it tries to restart the embedded Python host and updates the
persistent notification.

Player traffic uses HTTP/1.1 keep-alive, TCP no-delay, gzip JSON responses, and
cached static assets. The Android owner status view reads a lightweight room
summary instead of serializing the complete game every second.

Some vendors still suspend foreground services under aggressive battery
management. If screen-off hosting remains interrupted, set the app battery mode
to **Unrestricted / Allow background activity**, turn off system battery saver
while hosting, and keep the permanent room notification enabled.

Local-only hotspot creation requires **Nearby Wi-Fi devices** on Android 13+
and location permission on Android 8–12. A system tethering hotspot cannot run
at the same time. On a player phone, choose **keep connected** if the system
warns that the Mahjong Wi-Fi has no Internet; normal Internet traffic can then
continue over that player's cellular data according to the player's OS routing
settings.

This is trusted-LAN HTTP. Account selection has no password and does not prevent another trusted participant from choosing the same account. Session tokens prevent request-body identity spoofing and stale simultaneous sessions, but they do not turn unencrypted LAN traffic into an Internet-safe service.

## Zeabur online lobby operations

Use `/battle-login` for player login and registration. Registration requires
an invite code. The default invite code is `WL1234`, and the registration page
fills it in as a masked value. All human accounts use the fixed password
`1234`; existing human account password hashes are rewritten on service
startup. Use `/battle/admin` after logging in as the administrator to
generate invite codes, inspect online visitors, review accounts, monitor rooms,
and close problem rooms.

If players report stale room state, close the affected room from the admin
dashboard. Closing a room during a hand intentionally cancels that hand and
sends players back to the lobby.

Monitor Zeabur Metrics for CPU, memory, and network. If CPU stays near 80% or
high AI causes visible pauses, keep `WENLING_DEFAULT_AI_POLICY=low`, reduce
active rooms, or increase service resources before considering a dedicated
server.

Run only one service instance for this release. Room state is in memory and the
SQLite database is mounted on one persistent volume, so horizontal scaling is
not supported.
