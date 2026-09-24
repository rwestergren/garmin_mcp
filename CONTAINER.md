# Gateway container

The fork publishes `ghcr.io/rwestergren/garmin-mcp:latest` and `sha-<full-commit>`
tags. Make the GHCR package public after its first publication. The container
uses upstream's native stateful Streamable HTTP server at `/mcp`, with
`GET /healthz` on `0.0.0.0:$PORT` (default 8080).

## Storage and authentication

Mount a private writable `/data` volume per installation. The rest of the
filesystem can be read-only. Tokens live in `/data/garmin/garmin_tokens.json`;
the auth CLI's additional base64 export lives at `/data/garmin_tokens_base64`.
The entrypoint uses umask `077`, including during token refresh writes.

```sh
docker volume create garmin-alice
docker run --rm -it --read-only \
  --cap-drop ALL --security-opt no-new-privileges \
  -v garmin-alice:/data \
  ghcr.io/rwestergren/garmin-mcp:latest garmin-mcp-auth

docker run --rm --read-only \
  --cap-drop ALL --security-opt no-new-privileges \
  --memory 256m --cpus 0.5 \
  -v garmin-alice:/data -e PORT=8080 -p 127.0.0.1:8080:8080 \
  ghcr.io/rwestergren/garmin-mcp:latest
```

Alternatively, provision a token document generated with the same pinned
Garmin dependency into `/data/garmin/garmin_tokens.json`, with directory mode
`0700` and file mode `0600`. Import it once; subsequent starts must preserve
the refreshed copy. Do not pass raw JSON through `GARMINTOKENS`: upstream logs
that value as a path. `/healthz` indicates HTTP readiness, not Garmin login success.

For a local source build, use `docker compose build`, then
`docker compose run --rm garmin-mcp garmin-mcp-auth` and `docker compose up -d`.
Existing Compose users must migrate tokens from the old `/root/.garminconnect`
layout into `garmin/` within the volume, or authenticate again.

The gateway must enforce one active runtime per installation and reuse it for
multiple MCP sessions. Session DELETE must not stop the container while other
sessions use it. Retain storage across idle reaping; delete it on installation
removal. Persistent storage contains bearer credentials and needs host-level
access control and encryption. The existing gateway runner needs this storage
and runtime-lifecycle capability before deploying this image.

## Tools

All upstream tools are enabled except `download_activity_file`,
`set_fit_download_dir`, `download_course_gpx`, and `upload_course`. These tools
require file transfer or local paths that remote clients cannot access.
API-backed writes and in-memory FIT analysis remain available. Upstream's
`GARMIN_ENABLED_TOOLS` overrides the denylist; leave it unset for these defaults.

The fork serializes Garmin calls, including direct client calls, so concurrent
sessions cannot race token refresh. A timed-out worker retains ownership until
its underlying call finishes; subsequent calls wait or return a timeout.

## Checks

### Live local validation

Use the published commit tag (or digest) instead of `latest` to validate a fixed
artifact. `garmin-local-data` below is an arbitrary Docker volume name for your
test account; Docker mounts it at `/data` inside the container.

```sh
IMAGE=ghcr.io/rwestergren/garmin-mcp:sha-<full-commit>
docker pull "$IMAGE"
docker volume create garmin-local-data

docker run --rm -it --read-only \
  --cap-drop ALL --security-opt no-new-privileges \
  -v garmin-local-data:/data "$IMAGE" garmin-mcp-auth

docker run --rm --read-only \
  --cap-drop ALL --security-opt no-new-privileges \
  -v garmin-local-data:/data "$IMAGE" garmin-mcp-auth --verify

docker run -d --name garmin-local --read-only \
  --cap-drop ALL --security-opt no-new-privileges \
  --memory 256m --cpus 0.5 \
  -v garmin-local-data:/data -e PORT=8080 -p 127.0.0.1:8080:8080 \
  "$IMAGE"

curl --fail http://127.0.0.1:8080/healthz
npx @modelcontextprotocol/inspector
```

Enter your email, password, and MFA code only in the interactive auth command.
In Inspector, open the URL printed by the command, select **Streamable HTTP**,
and connect to `http://127.0.0.1:8080/mcp`. List tools, then call `get_devices`
and `get_stats` with a recent date. Verify the returned data matches your
account; a successful health probe alone does not verify authentication.
All compatible write tools are present, so use read tools for this smoke check.

To verify persistence, run `docker stop garmin-local` and
`docker rm garmin-local`, then repeat the server `docker run` command above
with the same volume and image. Reconnect Inspector and repeat the read calls;
no login prompt should be needed. Repeat after normal access-token expiry to
exercise a real refresh and subsequent cold start. Do not run a second server
or the auth/verify commands against this volume while the first server runs.

Use `docker stats --no-stream garmin-local` to inspect memory consumption.
Live MFA and token refresh are account-specific checks; automated tests use a
fake backend. If reauthentication is needed, stop the server and rerun the auth
command with `--force-reauth`, then start it again.

Stop and remove the test container when finished. Keep the volume for future
tests, or deliberately remove its saved credentials with
`docker volume rm garmin-local-data` after removing the container.

### Automated checks

```sh
uv run pytest tests/unit tests/integration
docker build -t garmin-mcp:test .
python3 tests/container/smoke.py garmin-mcp:test
```

The container check uses a fake Garmin HTTP backend, real token-file loading
and refresh, and the production entrypoint. Live Garmin login/MFA and large
FIT-analysis memory usage still require an account-specific check.
