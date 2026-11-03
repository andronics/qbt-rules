# Troubleshooting

## Diagnostics

- **Configuration check:** `docker exec qbt-rules qbt-rules --validate` checks `config.yaml` and `rules.yml` without running anything.
- **What the container resolved:** `docker exec qbt-rules env | grep QBT_RULES_`, and the files in the state directory (`/var/lib/qbt-rules`).
- **More logging:** `QBT_RULES_LOGGING_LEVEL=DEBUG` on the server, or `--log-level DEBUG --trace` on a single client run.
- **Health:** `curl http://127.0.0.1:5000/api/health`: `200` and `"status": "healthy"`, or `503` with an `errors` array naming what's wrong.
- **Container:** `docker logs qbt-rules`, and `docker inspect --format '{{json .State.Health}}' qbt-rules`.

### Debugging Commands

#### Check qBittorrent API access

```bash
# Test authentication
curl -X POST "http://localhost:8080/api/v2/auth/login" \
  -d "username=admin&password=your_password"

# Get torrent list
curl -X GET "http://localhost:8080/api/v2/torrents/info" \
  --cookie "SID=your_session_id"

# Get specific torrent details
curl -X GET "http://localhost:8080/api/v2/torrents/properties?hash=TORRENT_HASH" \
  --cookie "SID=your_session_id"
```

#### Test config file syntax

```bash
# Use the built-in validator (checks both config.yaml and rules.yml)
docker exec qbt-rules qbt-rules --validate
```

#### Test the server is healthy

```bash
# Server health endpoint
curl http://localhost:5000/api/health

# Reported version
docker exec qbt-rules qbt-rules --version

# Which image tag is actually running
docker inspect qbt-rules --format '{{.Config.Image}}'
```

#### Run with maximum verbosity

```bash
# Enable all logging for a single job
docker exec qbt-rules qbt-rules --trace --dry-run --context manual --wait

# Or with DEBUG log level
docker exec qbt-rules qbt-rules --trace --log-level DEBUG --dry-run --context manual --wait
```

#### Check the container environment

```bash
# Confirm the container is running and its uptime
docker ps --filter name=qbt-rules

# Check what config/env values the container actually resolved
docker exec qbt-rules env | grep QBT_RULES_

# Tail container logs directly
docker logs -f qbt-rules
```

### Log Analysis

#### Understanding log levels

```text
[DEBUG]  # Development information (not shown by default)
[INFO]   # Normal operation messages
[WARNING]  # Potential issues that don't stop execution
[ERROR]  # Errors that prevent specific actions
[TRACE]  # Detailed execution flow (--trace flag required)
```

#### Common log messages

**Normal operation:**

```text
[INFO] Loaded 5 rules from config/rules.yml
[INFO] Processing 42 torrents
[INFO] Rule "Remove old torrents" matched torrent "Example.Torrent"
[INFO] Executing action: delete_torrent
[INFO] Deleted torrent: Example.Torrent (hash: abc123...)
```

**Idempotent skips (normal):**

```text
[INFO] Torrent already stopped, skipping
[INFO] Category already set to 'Movies', skipping
[INFO] Tag 'auto' already exists, skipping
```

**Errors:**

```text
[ERROR] Failed to delete torrent abc123: 404 Torrent not found
[ERROR] Invalid category name: 'Invalid/Category'
[ERROR] Connection timeout after 30s
```

**Trace mode (debugging):**

```text
[TRACE] Fetching trackers for torrent: abc123
[TRACE] API call: /api/v2/torrents/trackers?hash=abc123
[TRACE] Response: [{'url': 'udp://tracker.example.com:80', ...}]
[TRACE] Evaluating condition: trackers.url contains "example.com"
[TRACE] Result: True
```

## Common problems

### Settings, rules or jobs gone after upgrading

0.11 no longer reads `/config`, with no fallback: config is in `/etc/qbt-rules` (`config.yaml`, `rules.yml`) and state in `/var/lib/qbt-rules` (`qbt-rules.db`, `.history/`). A container that still mounts only `/config` starts with no rules, no API key and an empty queue. Copy each file to its new place: see [In-Depth Configuration](In-Depth-Configuration#migrating-from-010x). A setting left pointing under `/config`, `engine.dry_run`, `CONFIG_DIR` or `QBT_RULES_CONFIG_DIR` stops the server at startup with a message naming the fix.

### Container shows "unhealthy" after changing the port

The image's healthcheck polls `QBT_RULES_LISTEN_PORT` (default `5000`). `QBT_RULES_SERVER_PORT` is an alias the server accepts but the healthcheck doesn't read: set `QBT_RULES_LISTEN_PORT` instead.

### Every API request answers `503 No API key is configured`

The server started without `server.api_key` (or with the 0.10.x placeholder key, which is public and so ignored). `/api/health` lists it under `config_problems`. Set `QBT_RULES_SERVER_API_KEY_FILE` (or `QBT_RULES_SERVER_API_KEY`) and restart.

### `PUID and PGID must be numeric`

The entrypoint refuses non-numeric `PUID`/`PGID`. Give numbers (`1000`, Unraid's `99`/`100`), not user names.

### A `_FILE` variable's value isn't picked up

The file named by a `QBT_RULES_..._FILE` variable doesn't exist, or the process can't read it. Check the path inside the container, and the file's owner and mode: the server runs as `PUID:PGID` (default `1000:1000`).

### Issue: "Connection refused" to qBittorrent

**Symptoms:**

```text
ConnectionError: Failed to connect to qBittorrent at http://localhost:8080
```

**Solutions:**

1. **Check qBittorrent Web UI is running:**
   - Open `http://localhost:8080` in browser
   - If not accessible, enable Web UI in qBittorrent settings

2. **Verify host/port in config:**

   ```yaml
   qbittorrent:
     host: http://localhost:8080  # Match your qBittorrent Web UI
   ```

3. **Check firewall rules:**

   ```bash
   # Linux: Allow port 8080
   sudo ufw allow 8080
   ```

4. **For remote qBittorrent, use full URL:**

   ```yaml
   qbittorrent:
     host: http://192.168.1.100:8080
   ```

### Issue: Rules not matching expected torrents

**Symptoms:**

- Rule conditions look correct but torrents aren't matched
- No actions applied when they should be

**Debugging steps:**

1. **Enable trace mode:**

   ```bash
   docker exec qbt-rules qbt-rules --dry-run --context manual --trace --wait
   ```

2. **Check condition evaluation:**

   ```text
   [TRACE] Rule: "Remove old torrents"
   [TRACE]   Condition: info.ratio >= 2.0
   [TRACE]   Result: False (actual: 1.5)
   [TRACE]   Rule skipped
   ```

3. **Verify field values:**

   ```bash
   # Check actual field values
   curl -X GET "http://localhost:8080/api/v2/torrents/info" \
     --cookie "SID=your_session_id"
   ```

4. **Common mistakes:**
   - Wrong field name (`info.name` not `info.torrent_name`)
   - Wrong operator (`==` for exact match, `contains` for substring)
   - Wrong value type (string `"1.0"` vs float `1.0`)
   - Collection fields not understood (see [Conditions](Conditions#collection-field-behavior))

### Issue: Actions not being applied

**Symptoms:**

- Conditions match but actions don't execute
- Logs show "skipping" messages

**Possible causes:**

1. **Dry-run mode enabled:**

   ```bash
   # Remove --dry-run to apply changes
   docker exec qbt-rules qbt-rules --context manual --wait
   ```

2. **Idempotent action already applied:**

   ```text
   [INFO] Torrent already stopped, skipping
   [INFO] Category already set to 'Movies', skipping
   ```

   This is normal behavior - action was already applied previously.

3. **Earlier rule matched with `stop_on_match: true`:**

   ```yaml
   - id: first-rule
     stop_on_match: true  # Prevents later rules from running
   ```

4. **Invalid action parameters:**

   ```text
   [ERROR] Invalid category name: 'Invalid/Category'
   ```

   Check parameter validation in logs.

### Issue: Regex patterns not matching

**Symptoms:**

- `matches` operator not finding expected torrents
- Pattern works in regex tester but not in rules

**Solutions:**

1. **Use raw strings in YAML:**

   ```yaml
   # Wrong: Backslashes interpreted by YAML
   value: '\d+'

   # Right: Single quotes preserve backslashes
   value: '(?i).*\d+.*'
   ```

2. **Test regex patterns:**

   ```python
   import re

   pattern = r"(?i).*[Ss]\d{2}[Ee]\d{2}.*"
   test_string = "Show.Name.S01E05.1080p"
   print(re.match(pattern, test_string))  # Should match
   ```

3. **Use `(?i)` for case-insensitive:**

   ```yaml
   - field: info.name
     operator: matches
     value: '(?i).*sample.*'  # Matches "Sample", "SAMPLE", "sample"
   ```

4. **Escape special characters:**

   ```yaml
   # To match literal dots
   value: '.*\.mkv$'  # Matches ".mkv" extension
   ```

### Performance Issues

#### Slow execution with many torrents

**Symptoms:**

- Rules take minutes to run
- High API call volume

**Solutions:**

1. **Put cheap `info.*` checks first in `all:`** (no separate pre-filter exists — `all()` evaluation short-circuits, so expensive fields later in the list never run once an earlier check fails):

   ```yaml
   conditions:
     all:
       - field: info.category
         operator: "=="
         value: "Movies"
       - field: info.state
         operator: "=="
         value: "downloading"
   ```

2. **Avoid expensive fields:**

   ```yaml
   # Fast: Uses cached info.* data
   - field: info.ratio
     operator: ">="
     value: 2.0

   # Slow: Requires API call per torrent
   - field: files.name
     operator: contains
     value: "sample"
   ```

3. **Use `stop_on_match`:**

   ```yaml
   - id: first-match-wins
     stop_on_match: true  # Don't evaluate remaining rules
   ```

4. **Run less frequently:**

   ```bash
   # Cron: Every 6 hours instead of hourly
   0 */6 * * * curl -s -X POST -H "X-API-KEY: $QBT_RULES_API_KEY" "http://qbt-rules:5000/api/execute?context=scheduled"
   ```

5. **Increase worker concurrency** if multiple jobs are queuing up faster than they're processed:

   ```yaml
   # config.yaml
   server:
     workers: 4  # default is 1
   ```

#### High memory usage

**Symptoms:**

- Container using excessive RAM
- Out of memory errors

The engine already evaluates torrents one at a time rather than loading everything into memory for batch processing, so memory use should stay flat regardless of library size. If you're still seeing high memory:

1. **Check the queue backend** — a very large backlog of completed jobs in SQLite/Redis can grow the queue database over time; confirm `queue.cleanup_after` (in `config.yaml`) is set to prune old job records
2. **Check for a stuck/looping job** via `--list-jobs` — a job retried indefinitely will keep accumulating log data
3. **Reduce `server.workers`** if multiple concurrent large jobs (each holding their own per-job torrent-list cache) are running at once on a memory-constrained host
