# Standalone read-only deployment

One container, Docker Compose, no Kubernetes and no Home Assistant add-on. The same directory runs on sda-apps, a home Proxmox VM, or a cabin Proxmox VM. Moving it is an edit to the files in this directory, not an image rebuild and not a chart change.

The process is read-only twice. `MCP_UNIFI_READONLY` is the literal `true` in both compose files, and the entrypoint sets it again after Docker applies the environment, so `.env` and a `docker compose run -e` flag cannot turn writes on. Changing that requires editing the compose file. Pair it with a view-only UniFi API key. The flag decides what this server will attempt. The key decides what the gateway will accept.

Nothing in this directory talks to a gateway until you start the container. Starting it is an operator action. This repository's automation does not start it.

## Sizing

Start with a **2 GB VM** or a **1 GB LXC**. The compose file limits the container to **512 MB**.

Those host sizes are a suggestion, not a measurement. The image is Debian slim plus the locked Python dependencies, and the host also runs Docker and, usually, Tailscale. After the first real client session, read `docker stats` and the host's available memory. If the container's working set sits near 512 MB, or the host is swapping, raise the VM or the LXC. Do not treat 512 MB as a benchmark.

An LXC that runs Docker needs whatever nesting or socket setup your Proxmox host already uses for Docker. This stack uses `network_mode: host`, so the address in `BIND_ADDR` must be an address on that LXC or VM, not an address that exists only on the hypervisor.

## What you edit

| Goal | Edit |
|---|---|
| Run the container on a different machine | `BIND_ADDR` in `.env`, then `docker compose up -d` on that machine |
| Talk to a different gateway | `host` (and `site` if it is not `default`) in `controllers.yaml`, the matching file under `secrets/`, and a new pin under `pins/` |
| Add or remove a gateway | The controller entry, its `secrets/unifi_api_key_<name>` file, and the `secrets:` blocks in both compose files. Those three stay in lockstep |
| Listen on a different port | `MCP_PORT` in `.env` |
| Use a locally built image | `MCP_UNIFI_IMAGE` in `.env` |

`BIND_ADDR` is required. The HTTP compose file has no default for it. Set it to this machine's Tailscale IPv4 address (`tailscale ip -4`). The process binds that address with host networking. This file does not publish a Docker port. A published port with no address listens on every host address, which this deployment does not do.

## Layout

```text
deploy/compose/
  docker-compose.yml           HTTP. Read-only is hardcoded.
  docker-compose.stdio.yml     stdio alternative. No HTTP listener.
  .env.example                 Non-secret settings. Copy to .env.
  controllers.example.yaml     Gateways. Copy to controllers.yaml.
  secrets/README               Tracked. Real secret files are gitignored.
  pins/                        PEM files from mcp-unifi-pin-cert. Gitignored.
```

`controllers.yaml` and `.env` are gitignored. Create them before the first `docker compose` command. The controllers mount sets `create_host_path: false`, so a missing file fails the start instead of Docker creating a directory at that path.

## View-only admin and API key

The key path this project documents is **Settings → Control Plane → Integrations → Create API Key**. UniFi OS labels move between versions. The requirement is a local admin whose Network permission is view only, and a key created under that authority.

1. On the gateway, add a local administrator. Use a console-local account, not an SSO-only ui.com user.
2. Give that admin the Network role **View Only**. Do not assign Super Admin or Site Admin.
3. Sign in as that admin.
4. Open **Settings → Control Plane → Integrations → Create API Key**.
5. Put the key, one line and no quotes, in `secrets/unifi_api_key_home` or `secrets/unifi_api_key_cabin`. `chmod 400` the file. The console shows the key once.
6. Sign back in as your own admin and confirm the new account is still View Only.

A key created by a super admin is not view-only. This server's read-only flag does not change what the key is allowed to do on the gateway. Some firmware builds only let a full admin open the Integrations screen, and the key then inherits that admin. If you cannot confirm the key is view-only in the console, do not point this stack at that gateway.

This server has no tool that reports the key's privilege. A successful read is not that confirmation.

Mint the bearer token separately. It authenticates MCP clients, not the gateway:

```bash
umask 077
openssl rand -hex 32 > secrets/mcp_unifi_token
chmod 400 secrets/mcp_unifi_token
```

## Pin a gateway certificate

`verify_ssl: true` uses the image's system trust store. A UniFi console presents its own certificate, which is not in that store, so the controllers file also sets `pinned_cert`. The pin is the only trust anchor for that controller: the console must present that certificate, and anything else fails closed. Hostname matching is off because the pin is the identity.

There is no CA-bundle setting. A certificate signed by a private CA is pinned the same way: record the certificate the console presents. Do not set `verify_ssl: false`. The server rejects `pinned_cert` together with `verify_ssl: false`.

Create the secret files and `controllers.yaml` first, so Compose can mount them. Then, from this directory, with `BIND_ADDR` set in `.env`:

```bash
mkdir -p pins
docker compose run --rm --no-deps --user 1000:1000 \
  --entrypoint mcp-unifi-pin-cert \
  -v "$PWD/pins:/pins" \
  mcp-unifi <gateway-host> --out /pins/home.pem
```

The command prints the SHA-256 fingerprint. Compare it with the certificate the console shows you, or with the certificate you see when you open `https://<gateway-host>` in a browser, before you treat the file as the pin. To require a fingerprint you already wrote down, add `--expect-fingerprint <sha256>`.

The running service mounts `./pins` read-only at `/etc/mcp-unifi/pins`. `controllers.yaml` points `pinned_cert` at `/etc/mcp-unifi/pins/home.pem` (and `cabin.pem` for the second gateway).

When a firmware update regenerates the certificate, every request fails closed until you re-pin. Run the same command with `--force` and check the new fingerprint before you do.

## First start

```bash
cp .env.example .env
cp controllers.example.yaml controllers.yaml
# edit .env (BIND_ADDR) and controllers.yaml (host, site)
# write secrets/ and pins/ as above

# Only needed for the published 0.27.0 image, and only the first time
# this named volume is created. See "Audit log" below.
docker run --rm --user root --entrypoint chown \
  -v mcp-unifi-audit-log:/var/lib/mcp-unifi \
  ghcr.io/pete-builds/mcp-unifi:0.27.0 \
  1000:1000 /var/lib/mcp-unifi

docker compose up -d
docker compose ps
docker compose logs -f mcp-unifi
```

Clients use `http://<BIND_ADDR>:<MCP_PORT>/mcp` and `Authorization: Bearer` with the contents of `secrets/mcp_unifi_token`. `/health` on the same host and port is the unauthenticated health check.

`STUB_MODE=true` does not skip `api_key_file` or `pinned_cert` validation when `controllers.yaml` names those paths. This stack is the real-mode deployment. A no-hardware demo is the stub `docker run` in the repository README, not this directory.

## Stdio alternative

`docker-compose.stdio.yml` is the same container without an HTTP listener and without the bearer token. The process speaks MCP on stdin and stdout. The parent process is the security boundary. Read-only is hardcoded the same way.

```bash
docker compose -f docker-compose.stdio.yml run --rm --no-deps mcp-unifi
```

Do not `up -d` that file. `restart` is `no`, and the health check is disabled because there is no port to probe. Point a stdio MCP client at that `run`. The audit log still goes to the named volume.

## Audit log

The log is a named volume mounted at `/var/lib/mcp-unifi`. Both compose files set the volume's name to `mcp-unifi-audit-log`, so the HTTP service and the stdio service append to the same log. The path inside the container is `/var/lib/mcp-unifi/audit.jsonl` (`MCP_UNIFI_AUDIT_SINK=file`). One JSON object per line, secrets scrubbed. An audit-log write failure is logged and does not fail the tool call.

The image runs as uid 1000. A named volume is owned by root unless something else sets the owner.

- A image built from this repository's Dockerfile contains `/var/lib/mcp-unifi` owned by uid 1000. The first time Docker creates the volume from that image, it seeds the ownership, and no chown is required.
- `ghcr.io/pete-builds/mcp-unifi:0.27.0` does not have that directory. Run the `docker run --user root --entrypoint chown` command in "First start" once, before the first `up`, or the log file cannot be created. An existing volume is not re-seeded when you later switch images. If logs contain `audit sink write failed`, run the chown against that volume and recreate the container.

Read the log from the host:

```bash
docker run --rm -v mcp-unifi-audit-log:/var/lib/mcp-unifi:ro alpine \
  cat /var/lib/mcp-unifi/audit.jsonl
```

## Repoint

**Another machine** (sda-apps, the home VM, the cabin VM):

1. Install Docker and Tailscale on that machine.
2. Copy this directory, including `secrets/` and `pins/`, or re-pin if you would rather not copy PEM files.
3. Set `BIND_ADDR` to `tailscale ip -4` on the new machine.
4. `docker compose up -d`.

The gateway addresses in `controllers.yaml` stay as they are if those gateways are reachable from the new machine (LAN or Tailscale). No image rebuild.

**Another gateway:**

1. Change that controller's `host` and, if needed, `site` in `controllers.yaml`.
2. Replace `secrets/unifi_api_key_<name>` with a view-only key from the new gateway.
3. Re-pin into `pins/<name>.pem`. Use `--force` only when you intend to replace a pin, and check the fingerprint first.
4. `docker compose up -d --force-recreate`.

Recreate restarts this container. It does not change the gateway.

## Hardening

| Control | Where |
|---|---|
| Read-only tools | `MCP_UNIFI_READONLY: "true"` and the entrypoint assignment. Both compose files. |
| Non-root | `user: "1000:1000"`. The image's `USER` is the same uid. |
| Read-only root filesystem | `read_only: true`. `/tmp` is a 16 MB tmpfs. |
| Capabilities | `cap_drop: [ALL]` |
| No new privileges | `no-new-privileges:true` |
| Memory | `mem_limit: 512m` and `deploy.resources.limits.memory: 512M` |
| Restart | `unless-stopped` on the HTTP file. `no` on stdio. |
| Health | HTTP file probes `http://$MCP_HOST:$MCP_PORT/health`, the address the process bound. The image's own check uses localhost, which is the wrong address when the process is bound to a Tailscale IP. |
| Secrets | Docker secret files only. No `env_file`. No `UNIFI_API_KEY` or `MCP_UNIFI_AUTH_TOKENS` in the environment. |
| TLS | `verify_ssl: true` and `pinned_cert` on every controller. |
| Audit | Named volume `audit-log`. |

## Helm

The Helm chart's `readOnly` value now defaults to `true`, because the chart sets `MCP_UNIFI_READONLY` explicitly and the old default of `false` overrode the image. This directory is the supported standalone deployment. The chart is unchanged apart from that default. Set `readOnly: false` in the chart's `values.yaml` only for a deployment that is allowed to write.
