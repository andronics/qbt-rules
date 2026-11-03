qbt-rules can schedule its own recurring jobs internally — you don't need an external cron job, systemd timer, or sidecar container hitting the HTTP API on a schedule anymore (though that pattern still works fine if you prefer it; see [Contexts](Contexts#scheduledrecurring-contexts) for that approach).

### How It Works

A new `Scheduler` component runs inside the server process, structurally similar to the background [Worker](Architecture-Internals) — its own thread, checking a list of cron-style entries on a poll interval and enqueuing a job directly into the same queue every other job submission path uses (the HTTP API, the CLI client) when an entry's cron expression fires.

### Configuration

Add a `schedule:` list to `config.yaml`, alongside `server:`/`queue:`:

```yaml
schedule:
  - cron: "*/30 * * * *"   # Every 30 minutes
    context: cron
  - cron: "0 3 * * *"      # Daily at 3 AM
    context: nightly
```

Each entry needs:

| Field | Description |
|-------|-------------|
| `cron` | A standard 5-field cron expression (minute, hour, day-of-month, month, day-of-week) |
| `context` | The context string to submit — matched against rules' `context:` field exactly like any other job, see [Contexts](Contexts) |

Invalid entries (missing fields, an unparseable cron expression) fail server startup with a clear error rather than silently being skipped.

**Environment variable override** — since this is a list rather than a single value, it doesn't use a single `QBT_RULES_SCHEDULE_*` variable the way scalar config does. Instead, each entry is set via a pair of **indexed** variables, `QBT_RULES_SCHEDULE_<N>_CRON` and `QBT_RULES_SCHEDULE_<N>_CONTEXT` (each with the usual `_FILE` variant), starting at `N=0` and counting up contiguously — enumeration stops at the first missing index:

```bash
QBT_RULES_SCHEDULE_0_CRON="*/30 * * * *"
QBT_RULES_SCHEDULE_0_CONTEXT=cron
QBT_RULES_SCHEDULE_1_CRON="0 3 * * *"
QBT_RULES_SCHEDULE_1_CONTEXT=nightly
```

If **any** `QBT_RULES_SCHEDULE_0_CRON` is set, the environment-defined schedule **entirely replaces** `config.yaml`'s `schedule:` list — the two aren't merged, consistent with how every other field's environment variable overrides its `config.yaml` value outright. Setting `_0_CRON` without a matching `_0_CONTEXT` (or vice versa) fails server startup with a clear error, same as a malformed `config.yaml` entry.

It's also **not hot-reloaded**: unlike `rules.yml`, changes require a server restart to take effect (matching the rest of `config.yaml`, which is only read once at startup).

### What Happens When It Fires

Firing a scheduled entry is identical to a job submitted any other way — same queue, same worker, same job lifecycle (`pending` → `processing` → `completed`/`failed`), visible via `qbt-rules jobs list`/`jobs status` or the [HTTP API Reference](HTTP-API-Reference)'s `/api/jobs` endpoints. There's no separate "scheduled job" concept to track.

There's no misfire catch-up: if the server was down when a fire time passed, that occurrence is simply skipped — the same behavior an external cron job would have had.

### One Process, One Scheduler

The server is one process, and the scheduler is a thread in it, so each entry fires **exactly once per cron tick**. `server.workers` must be `1`. Run only one server per qBittorrent instance: a second one (another container, or a second Kubernetes replica) would fire every entry again. If the scheduler thread dies, `/readyz` answers `503` naming it (see [Deployment](Deployment#probes)).

### Migrating from an External Cron Job

If you're currently running something like:

```bash
*/30 * * * * curl -s -X POST -H "X-API-KEY: $QBT_RULES_API_KEY" "http://qbt-rules:5000/api/execute?context=cron"
```

The equivalent internal schedule entry is:

```yaml
schedule:
  - cron: "*/30 * * * *"
    context: cron
```

You can remove the external cron job (or sidecar container) once this is in place and confirmed working — check `qbt-rules jobs list` after the first expected fire time to confirm.
