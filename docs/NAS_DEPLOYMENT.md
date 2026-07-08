# NAS Docker deployment

This deployment keeps the Mahjong service isolated in Docker and exposes only
the game site through Cloudflare Tunnel. Do not expose the NAS management UI or
NAS shared folders to the public Internet.

## Files

- `Dockerfile` builds the Python game service image.
- `docker-compose.nas.yml` runs the game service and `cloudflared` on a private
  Docker network.
- `.env.nas.example` is a template for local NAS secrets. Copy it to `.env` and
  never commit the real `.env`.

## Cloudflare setup

1. Add the domain to Cloudflare and update the domain registrar nameservers.
2. In Cloudflare Zero Trust, create a Tunnel.
3. Choose Docker as the connector type and copy only the tunnel token.
4. Add a public hostname for the tunnel:
   - Type: `HTTP`
   - URL: `http://wenling-mahjong:8765`

## NAS setup with SSH

Create a dedicated folder on the NAS for this service, then clone the repo:

```bash
git clone https://github.com/wuhao-pyquant/wenlingmajong.git
cd wenlingmajong
cp .env.nas.example .env
mkdir -p data
```

Edit `.env` and set:

```env
WENLING_ADMIN_USERNAME=admin
WENLING_ADMIN_PASSWORD=replace-with-a-strong-password
WENLING_INVITE_CODES=7392,WL8K2
WENLING_MAX_ROOMS=3
WENLING_DEFAULT_AI_POLICY=low
CLOUDFLARE_TUNNEL_TOKEN=replace-with-cloudflare-tunnel-token
```

Start the containers:

```bash
docker compose -f docker-compose.nas.yml --env-file .env up -d --build
```

Check status and logs:

```bash
docker compose -f docker-compose.nas.yml ps
docker compose -f docker-compose.nas.yml logs -f wenling-mahjong
docker compose -f docker-compose.nas.yml logs -f cloudflared
```

## NAS setup with UGREEN Docker app

If you do not use SSH, create a Docker project in the UGREEN Docker app and
paste the contents of `docker-compose.nas.yml`. Add the environment variables
from `.env.nas.example` in the project settings, or upload a `.env` file if the
app supports it. Keep the project folder dedicated to this service so `./data`
maps only to this game database and logs.

## Verification

After Cloudflare reports the tunnel is healthy, open:

```text
https://your-domain.example/battle-login
https://your-domain.example/battle/admin
https://your-domain.example/api/health
```

If you need temporary LAN-only testing, add this to the `wenling-mahjong`
service and remove it after testing:

```yaml
ports:
  - "8765:8765"
```

Then open `http://NAS-LAN-IP:8765/battle-login`.

## Update

```bash
git pull
docker compose -f docker-compose.nas.yml --env-file .env up -d --build
```

Back up only the dedicated `data` directory. It contains the SQLite database,
room logs, and account backups.
