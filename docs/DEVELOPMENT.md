# Development

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

For a second-device test, allow the selected TCP port through Windows Firewall, obtain the PC IPv4 address, and use the full `http://<address>:<port>` URL.

Apply shared-core changes as identical Git patches and verify `CORE_MANIFEST.json` in all repositories. Never import another split repository at runtime.

## Android build

The Android module uses Chaquopy 17 with Python 3.12 and packages the repository's `src`, `packages/wenling_core`, and `static` sources directly.

```powershell
gradle -p android-host :app:assemblePhoneDebug
gradle -p android-host :app:assembleEmulatorDebug
```

`phoneRelease` is arm64-only. `emulatorDebug` is x86_64. Android instrumentation and physical WiFi/hotspot validation require an installed SDK and device or emulator; the Python bridge is covered by the normal unittest suite.

The app has two host connection modes. `ConnectionMode.HOTSPOT` owns a
`LocalOnlyHotspotReservation` for the full foreground-service lifetime;
`ConnectionMode.LAN` uses the phone's existing Wi-Fi/Ethernet interfaces. Do
not start the embedded Python server before the hotspot callback reports
`onStarted`, because the displayed room address would otherwise be stale.
