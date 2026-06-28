# Wenling LAN Mobile Foundation

Authoritative PC host for browser clients on the same LAN, with a future Android WebView integration boundary.

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

## Test

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

This stage does not create an Android project and contains no Cloudflare dependency.
