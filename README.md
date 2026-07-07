# Wenling LAN Android Host

Authoritative Wenling Mahjong host for browser clients on the same LAN. The repository now contains both a desktop Python host and an Android owner console which embeds the same Python server.

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

## Run

```powershell
.\.venv\Scripts\python.exe -m wenling_lan_host --host 0.0.0.0 --port 8765
```

Open `http://<PC-LAN-IP>:8765/battle-login` on another device. Host metadata is available at `/api/host/info`.

Players may register a Chinese or Latin username of up to 12 characters from the
LAN login page. The owner is not a special player account: owner authority comes
from the Android in-process console or the PC loopback-only admin page. Player
registration and post-settlement random reseating are public; forced seat
management, account administration, and statistics mutation remain owner-only.

## Android

Prerequisites:

- Android Studio with Android SDK 36 and a compatible JDK.
- A 64-bit Android 7.0+ phone for `phoneDebug` / `phoneRelease`, or an x86_64 emulator for `emulatorDebug`.
- Python 3.12 available on the build machine for Chaquopy packaging.

Open `android-host` in Android Studio, sync Gradle, then build `phoneDebug`:

```powershell
gradle -p android-host :app:assemblePhoneDebug
```

For command-line-only setup, install Android platform 36 and build-tools 36.0.0 with `sdkmanager` after reviewing and accepting the Android SDK license, then set `ANDROID_HOME` / `ANDROID_SDK_ROOT` to that SDK directory.

Install the APK, create player accounts while the room is closed, then select a
connection mode:

- **手机专用热点** creates a local-only Wi-Fi network from the owner phone.
  Players first scan the Wi-Fi QR code and then the room QR code. This mode
  needs Android 8.0+ and does not share the owner's Internet connection.
- **外部局域网路由器** uses an existing Wi-Fi router. The owner and every
  browser player must connect to the same LAN.

The app remembers the selection. Stop the room before switching modes.
After the room starts, the owner can tap **房主在本机浏览器参战**. This opens
`http://127.0.0.1:8765/battle-login` on the owner device, where the owner joins
as an ordinary player account while administrative controls remain in the
Android console.

## Test

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The Android app does not auto-start after boot. Stopping the foreground room service invalidates all browser sessions; durable account and statistics data remains in the app-private runtime directory.

During an active room, the Android foreground service keeps the CPU and Wi-Fi
radio awake so browser play can continue with the host app backgrounded or the
screen locked. Android 10+ uses the low-latency Wi-Fi lock; older supported
versions use the high-performance lock. This intentionally consumes more
battery; stop the room when it is no longer needed.

The bundled hand-luck model scores all four players after every completed hand. Settlement shows each single-hand score, player statistics show the current-room average, and the owner database shows the persisted historical average.

## Zeabur Online Deployment

The online lobby runs as a single Python service with SQLite on a persistent
volume. Configure a Zeabur volume at `/data`, then set these environment
variables:

- `WENLING_DATA_DIR=/data`
- `WENLING_ADMIN_USERNAME=<admin name>`
- `WENLING_ADMIN_PASSWORD=<admin password>`
- `WENLING_INVITE_CODES=7392,WL8K2`
- `WENLING_MAX_ROOMS=3`
- `WENLING_DEFAULT_AI_POLICY=low`

Zeabur injects `PORT`; the service reads it automatically. The first startup
creates a fresh online database, initializes fixed AI accounts, creates or
updates the admin account, and imports the initial invite codes.

This release is intentionally single-instance. Do not horizontally scale it:
room state is in memory and SQLite is mounted on one persistent volume.
