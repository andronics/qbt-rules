# Security

qbt-rules acts directly on your qBittorrent instance — deleting torrents, changing categories, throttling bandwidth — based on rules you write and jobs anyone with your API key can submit. This page covers what to lock down, what qbt-rules can and can't protect you from, and a known gap worth designing around.

## Threat model

qbt-rules is a **rules engine acting on metadata**, not a content scanner. It's useful for security-adjacent automation (blocking unwanted file types on import, quarantining suspicious torrents for review) but it has real limits:

- **It doesn't inspect file contents.** Every condition operates on metadata qBittorrent already exposes — file names, sizes, tracker URLs, state — never the bytes inside a file. A rule matching `files.name` against `.exe` catches a file *named* `installer.exe`; it can't detect a renamed or archived payload.
- **It's not a replacement for antivirus or a firewall.** Treat it as one layer in a defense-in-depth setup: automation that reduces exposure window and enforces policy, not a guarantee nothing bad gets through.
- **Its blast radius is qBittorrent-wide.** Anyone who can submit a job (see API Authentication below) can trigger any action any rule is capable of — including `delete_torrent`. Protecting job submission is as important as writing good rules.

**What's exposed:** one HTTP port (default `5000`) serving the JSON API, the dashboard and, when enabled, `/metrics`. Everything on it except `GET /api/health` and `GET /api/version` needs the API key (or a dashboard session made with it). The server trusts the qBittorrent instance it's pointed at, the Sonarr/Radarr/trackie URLs you configure, and `rules.yml`, which anyone holding the key can rewrite through the rules editor.

### Content-Safety Rules

A common use of qbt-rules is blocking unwanted or dangerous file types before they finish downloading. A minimal pattern:

```yaml
- id: block-executable-payloads-on-import
  context: torrent-imported
  conditions:
    any:
      - field: files.name
        operator: matches
        value: '(?i)\.(exe|scr|bat|cmd|msi|vbs|js)$'
  actions:
    - type: stop
    - type: add_tag
      params:
        tags: ["quarantined", "needs-review"]
```

This only checks file *names* — it's a policy filter, not malware detection, and it inherits the metadata-timing gap described next. Pair it with a manual review step (the `needs-review` tag above) rather than auto-deleting; a false positive on a legitimately-named file is far less costly than an automated delete you can't undo.

### Known Limitation: Magnet-Link Metadata Timing

If a torrent is added by magnet link, its file list isn't known yet at the exact instant a `torrent-imported` webhook fires — qBittorrent hasn't fetched the metadata from peers/DHT. Any rule that inspects `files.*` (like the content-safety rule above) can get a false negative if it's *only* allowed to run in that context: the files simply aren't visible yet, so the condition never matches, and the torrent proceeds unblocked.

For security-sensitive rules that depend on file contents:

- **Omit `context:` entirely** so the rule re-evaluates on every job, including a recurring cron sweep that will catch it later once the file list is known, or
- **List every context that could plausibly re-check it** — `context: [torrent-imported, download-finished]` — so at least one later evaluation has the metadata available.

A `torrent-imported`-only content filter is a best-effort first pass, not a guarantee. See [Contexts](Contexts) for the full context-matching model this depends on.

## Secrets

- Give each secret through `QBT_RULES_<SECTION>_<FIELD>_FILE`, a mounted file. A secret setting is also read from its plain variable and `config.yaml`, like any setting, so keep it out of both: `docker inspect` and `ps` show variables. See [In-Depth Configuration](In-Depth-Configuration#secrets) for the list of secrets and what each grants.
- CI scans every commit with gitleaks, and secrets in history fail the build.
- The dashboard's config view (`/api/config/source`) masks credentials.

### API Authentication

`server.api_key` (or `QBT_RULES_SERVER_API_KEY`) gates every `/api/execute` call. Without it, anyone who can reach the server's port can queue jobs — which means they can trigger any action in `rules.yml` against your qBittorrent instance, including deletions. Treat this key like a qBittorrent Web UI password:

- Generate it with something like `openssl rand -hex 32` — don't hand-type a short string.
- Set it via the `_FILE`-suffixed env var (`QBT_RULES_SERVER_API_KEY_FILE`) from a Docker/Compose secret rather than a plaintext environment variable, so it never appears in `docker inspect` output or shell history.
- `client.api_key` (used by the CLI client) must match `server.api_key` exactly — a mismatch fails auth the same way a wrong password would.
- Rotate it by updating the secret and recreating the container; there's no separate revocation mechanism, so a leaked key is valid until you change it.

The [Dashboard](Dashboard) (`/`, `/jobs`, `/rules`, `/rules/edit`) reuses this same key: its login form exchanges it for a session cookie, and `?key=` in the URL works too — see the Dashboard page for the browser-history trade-off that implies, and why dashboard requests are excluded from the access log by default. A session can also save `rules.yml` from the editor, so treat a signed-in browser like the key itself; `server.editor_enabled: false` turns saving off.

The optional [`/metrics`](Metrics) endpoint (off by default) also requires this same key, via query param or `X-API-Key` header — unlike the dashboard, a scrape client typically sends the key as a header rather than a URL, so the browser-history trade-off doesn't apply there. What it exposes is operational counts (job throughput, error rates, HTTP request volume), not credentials — but that's still information you may not want reachable by anyone who can guess the port, hence the same API-key gate as everything else except `/api/health`/`/api/version`.

### Credential Management

Never hardcode qBittorrent credentials in `config.yaml`. Every config key has a matching `QBT_RULES_*` environment variable, and every one of those has a `_FILE`-suffixed counterpart that reads the value from a file — the standard pattern for Docker/Compose secrets:

```bash
# Plaintext env var — fine for local testing, avoid in production
export QBT_RULES_QBITTORRENT_PASSWORD="secure_password"

# File-based secret — preferred for production
export QBT_RULES_QBITTORRENT_PASSWORD_FILE="/run/secrets/qbt_password"
```

Resolution order is CLI args → `_FILE` env var → direct env var → config file → default, so a secret always wins over whatever's left in `config.yaml`. See [In-Depth Configuration](In-Depth-Configuration) for the complete environment variable reference.

This applies beyond qBittorrent credentials too — a Discord/Slack webhook URL (set via `notifications.webhook_url` for the [`notify`](Actions#notify) action) embeds a bearer token in the URL path itself, just as sensitive as a password. Use the `_FILE` variant for it in production, the same as `qbittorrent.password`. The same goes for `integrations.sonarr.api_key`/`integrations.radarr.api_key` (used by the [`arr_blocklist`](Actions#arr_blocklist) action) — an arr API key grants full control over that instance's library and downloads, not just read access.

If you do keep any credential in `config.yaml` directly (not recommended), restrict the host file's permissions:

```bash
chmod 600 ./config/config.yaml
```

### Log Hygiene

`--trace` (or `logging.trace_mode: true`) logs every field access and API response, which can include tracker URLs with embedded passkeys, torrent names, and tag contents. Before sharing trace logs — in a bug report, a support channel, or a GitHub issue — scrub anything that looks like a tracker announce URL or credential, the same way you'd sanitize `config.yaml` before sharing it (see [Contributing](Contributing)'s issue-reporting guidance).

## Hardening

- **Container:** the entrypoint starts as root only to `chown` the state directory to `PUID:PGID` (default `1000:1000`), then drops to that user for good. [contrib/docker/compose.yml](https://github.com/andronics/qbt-rules/blob/main/contrib/docker/compose.yml) adds a read-only root filesystem, `no-new-privileges`, and drops every capability except the few the entrypoint needs (`CHOWN`, `SETUID`, `SETGID`, `DAC_OVERRIDE`, `FOWNER`).
- **Supply chain:** dependencies are pinned in `uv.lock` and updated weekly by Dependabot. GitHub Actions are pinned to commit SHAs.
- **Input:** `rules.yml` saved through the editor is validated first and refused with errors (`422`); saves need the ETag of the version they started from, and a session-authenticated save also needs the page's CSRF token. The login form's redirect target is reduced to a same-origin path.
- **No rate limiting or IP allowlisting** in the server itself: that's the reverse proxy's job (below).

### Network Exposure

Don't publish the server's port (default `5000`) directly to the internet. There's no built-in rate limiting or IP allowlisting — API-key auth is the only gate, and a brute-forced or leaked key gives full control. If you need to reach it remotely:

- Keep it on an internal Docker network alongside qBittorrent and only expose it to other containers that need it (Sonarr/Radarr, a cron sidecar).
- If remote access is genuinely required, put it behind a reverse proxy that adds its own authentication (Basic Auth, OAuth, mTLS) and TLS termination — don't rely on the API key as your only line of defense at the network edge.

## Reporting a vulnerability

Report privately through [GitHub security advisories](https://github.com/andronics/qbt-rules/security/advisories/new), never in a public issue.

If you find a security issue in qbt-rules itself (not a rule-writing mistake, but a flaw in the engine, server, or API), please don't file it as a public issue. Use GitHub's private "Report a vulnerability" flow under the repository's **Security** tab so it can be assessed before details are public. If that option isn't available, open a regular issue asking for a private contact channel rather than posting exploit details directly.
