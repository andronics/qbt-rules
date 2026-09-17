# qbt-rules v0.4.0 Implementation Plan

**Status**: In Progress
**Version**: 0.4.0
**Breaking Changes**: Yes
**Distribution Model**: Docker-only (PyPI discontinued)

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Architecture Overview](#architecture-overview)
3. [Configuration System](#configuration-system)
4. [API Specification](#api-specification)
5. [Database Schemas](#database-schemas)
6. [Implementation Phases](#implementation-phases)
7. [Testing Strategy](#testing-strategy)
8. [Success Criteria](#success-criteria)
9. [v0.6.0 Planning](#v060-planning)
10. [v0.7.0 Planning](#v070-planning)

---

## Executive Summary

### What's Changing

qbt-rules v0.4.0 represents a fundamental architectural transformation from a simple CLI tool to a client-server application with Docker-first distribution.

**Key Changes:**
- **Architecture**: CLI tool → Client-server with HTTP API + persistent job queue
- **Distribution**: PyPI package → Docker container only (ghcr.io)
- **Execution Model**: Direct execution → Queue-based job processing
- **Terminology**: "trigger" → "context" throughout codebase
- **qBittorrent Integration**: Direct API calls → qbittorrent-api package

### Why These Changes

1. **Webhook Support**: qBittorrent webhooks (running in different containers) can trigger qbt-rules via HTTP API
2. **Concurrency Safety**: Job queue prevents race conditions from simultaneous executions
3. **Multi-Version Support**: qbittorrent-api handles version differences automatically
4. **Docker-Native**: Better integration with containerized infrastructure
5. **Future-Ready**: Architecture supports GUI, cross-seeding, and advanced features

### Breaking Changes

- **Users must run qbt-rules server** - CLI becomes HTTP client
- **Configuration file structure changes** - New server/client sections required
- **All "trigger" references become "context"** - Rules must be updated
- **PyPI package discontinued** - Docker container only
- **New environment variable naming** - All follow `QBT_RULES_*` convention

---

## Architecture Overview

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         TRIGGER SOURCES                         │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐   │
│  │  qBittorrent │  │  Cron/Timer  │  │  Manual CLI Exec   │   │
│  │   Webhooks   │  │   Schedule   │  │                    │   │
│  └──────┬───────┘  └──────┬───────┘  └─────────┬──────────┘   │
│         │                 │                     │               │
│         └─────────────────┴─────────────────────┘               │
│                           │ HTTP POST                           │
└───────────────────────────┼─────────────────────────────────────┘
                            │
                            ▼
          ┌─────────────────────────────────────────┐
          │      HTTP API SERVER (Flask)            │
          │  ┌───────────────────────────────────┐  │
          │  │  POST /api/execute                │  │
          │  │  GET  /api/jobs                   │  │
          │  │  GET  /api/jobs/{id}              │  │
          │  │  DELETE /api/jobs/{id}            │  │
          │  │  GET  /api/health                 │  │
          │  │  GET  /api/stats                  │  │
          │  └───────────────────────────────────┘  │
          │           │ API Key Auth                │
          └───────────┼─────────────────────────────┘
                      │
                      ▼
          ┌─────────────────────────────────────────┐
          │         PERSISTENT JOB QUEUE            │
          │  ┌────────────┐      ┌──────────────┐  │
          │  │   SQLite   │  or  │    Redis     │  │
          │  │  (default) │      │  (optional)  │  │
          │  └────────────┘      └──────────────┘  │
          │                                         │
          │  Jobs: pending → processing → completed │
          └───────────┬─────────────────────────────┘
                      │
                      ▼
          ┌─────────────────────────────────────────┐
          │        WORKER THREAD                    │
          │  ┌───────────────────────────────────┐  │
          │  │  1. Dequeue job                   │  │
          │  │  2. Update status: processing     │  │
          │  │  3. Execute RulesEngine           │  │
          │  │  4. Update result/error           │  │
          │  │  5. Mark completed/failed         │  │
          │  └───────────────────────────────────┘  │
          └───────────┬─────────────────────────────┘
                      │
                      ▼
          ┌─────────────────────────────────────────┐
          │         RULES ENGINE                    │
          │  (existing logic, no changes)           │
          │                                         │
          │  Context Filter → Torrent Filter →     │
          │  Rule Evaluation → Action Execution     │
          └───────────┬─────────────────────────────┘
                      │
                      ▼
          ┌─────────────────────────────────────────┐
          │    qBittorrent API (qbittorrent-api)   │
          │  • Multi-version support (v4.1 - v5.1+)│
          │  • Auto version detection               │
          │  • Auto authentication                  │
          └─────────────────────────────────────────┘
```

### Component Interactions

**Request Flow:**
1. **Client** (CLI, webhook, cron) → HTTP POST to `/api/execute?context=X&hash=Y&key=Z`
2. **API Server** validates API key → creates job → enqueues to queue → returns job ID
3. **Worker Thread** polls queue → dequeues job → updates status to "processing"
4. **RulesEngine** executes with context filter → evaluates rules → performs actions
5. **Worker** updates job with result/error → marks completed/failed
6. **Client** (optional) polls `/api/jobs/{id}` for status

**Queue Backend Selection:**
- **SQLite** (default): Zero dependencies, file-based, perfect for home users
- **Redis** (optional): High-performance, in-memory, for high webhook volume

---

## Configuration System

### Resolution Priority

All configuration follows this resolution order (highest to lowest):

1. **CLI flags** (e.g., `--server-port 5000`)
2. **Environment variable (_FILE variant)** (e.g., `QBT_RULES_SERVER_PORT_FILE=/secrets/port`)
3. **Environment variable (direct)** (e.g., `QBT_RULES_SERVER_PORT=5000`)
4. **Config file** (`config.yml`)
5. **Default value**

### Universal _FILE Support

**ALL environment variables support a `_FILE` variant** that reads the value from a file:

```bash
# Direct value
export QBT_RULES_SERVER_API_KEY="my-secret-key"

# File-based (reads content from file)
export QBT_RULES_SERVER_API_KEY_FILE="/run/secrets/api_key"
```

This works for **any setting**, not just secrets. Users decide what to externalize.

### Complete Configuration Reference

#### Server Configuration

| Environment Variable | CLI Flag | Config Key | Default | Description |
|---------------------|----------|------------|---------|-------------|
| `QBT_RULES_SERVER_HOST` | `--server-host` | `server.host` | `0.0.0.0` | Server bind address |
| `QBT_RULES_SERVER_PORT` | `--server-port` | `server.port` | `5000` | Server port |
| `QBT_RULES_SERVER_API_KEY` | `--server-api-key` | `server.api_key` | *(required)* | API authentication key |
| `QBT_RULES_SERVER_WORKERS` | `--server-workers` | `server.workers` | `1` | Gunicorn worker processes |

**All support _FILE variant**: `QBT_RULES_SERVER_HOST_FILE`, `QBT_RULES_SERVER_API_KEY_FILE`, etc.

#### Queue Configuration

| Environment Variable | CLI Flag | Config Key | Default | Description |
|---------------------|----------|------------|---------|-------------|
| `QBT_RULES_QUEUE_BACKEND` | `--queue-backend` | `queue.backend` | `sqlite` | Queue backend (sqlite/redis) |
| `QBT_RULES_QUEUE_SQLITE_PATH` | `--queue-sqlite-path` | `queue.sqlite_path` | `/config/qbt-rules.db` | SQLite database path |
| `QBT_RULES_QUEUE_REDIS_URL` | `--queue-redis-url` | `queue.redis_url` | - | Redis connection URL |
| `QBT_RULES_QUEUE_CLEANUP_AFTER` | `--queue-cleanup-after` | `queue.cleanup_after` | `7d` | Job retention period |

#### Client Configuration

| Environment Variable | CLI Flag | Config Key | Default | Description |
|---------------------|----------|------------|---------|-------------|
| `QBT_RULES_CLIENT_SERVER_URL` | `--client-server-url` | `client.server_url` | `http://localhost:5000` | Server URL for client |
| `QBT_RULES_CLIENT_API_KEY` | `--client-api-key` | `client.api_key` | *(required)* | API key for client |

#### qBittorrent Configuration

| Environment Variable | CLI Flag | Config Key | Default | Description |
|---------------------|----------|------------|---------|-------------|
| `QBT_RULES_QBITTORRENT_HOST` | `--qbittorrent-host` | `qbittorrent.host` | `http://localhost:8080` | qBittorrent Web UI URL |
| `QBT_RULES_QBITTORRENT_USERNAME` | `--qbittorrent-username` | `qbittorrent.username` | `admin` | qBittorrent username |
| `QBT_RULES_QBITTORRENT_PASSWORD` | `--qbittorrent-password` | `qbittorrent.password` | *(required)* | qBittorrent password |

#### Rules & Logging

| Environment Variable | CLI Flag | Config Key | Default | Description |
|---------------------|----------|------------|---------|-------------|
| `QBT_RULES_RULES_FILE` | `--rules-file` | `rules.file` | `/config/rules.yml` | Rules file path |
| `QBT_RULES_CONFIG_DIR` | `--config-dir` | `config.dir` | `/config` | Config directory |
| `QBT_RULES_LOG_LEVEL` | `--log-level` | `logging.level` | `INFO` | Log level (DEBUG/INFO/WARNING/ERROR) |
| `QBT_RULES_LOG_FILE` | `--log-file` | `logging.file` | `/config/qbt-rules.log` | Log file path |

### Example config.yml

```yaml
server:
  host: 0.0.0.0
  port: 5000
  api_key: your-secure-api-key-here
  workers: 1

queue:
  backend: sqlite  # sqlite or redis
  sqlite_path: /config/qbt-rules.db
  redis_url: redis://localhost:6379/0
  cleanup_after: 7d  # Keep completed jobs for 7 days

client:
  server_url: http://localhost:5000
  api_key: your-secure-api-key-here

qbittorrent:
  host: http://qbittorrent:8080
  username: admin
  password: adminpass

rules:
  file: /config/rules.yml

logging:
  level: INFO
  file: /config/qbt-rules.log
```

### Example rules.yml (with new "context" terminology)

```yaml
rules:
  - name: "Auto-categorize HD content on add"
    enabled: true
    stop_on_match: true
    conditions:
      context: on_added  # Changed from "trigger"
      all:
        - field: info.name
          operator: matches
          value: '(?i).*(1080p|2160p|4k).*'
    actions:
      - type: set_category
        params:
          category: "Movies-HD"
      - type: add_tag
        params:
          tag: "hd"

  - name: "Cleanup old completed torrents"
    enabled: true
    conditions:
      context: scheduled  # Run with: qbt-rules --context scheduled
      all:
        - field: info.state
          operator: in
          value: ["uploading", "pausedUP", "stalledUP"]
        - field: info.completion_on
          operator: older_than
          value: "30 days"
        - field: info.ratio
          operator: ">="
          value: 2.0
    actions:
      - type: delete_torrent
        params:
          delete_files: false

  - name: "Force seed low-seeded content"
    enabled: true
    conditions:
      context: scheduled
      all:
        - field: info.num_complete
          operator: "<="
          value: 2
        - field: info.state
          operator: in
          value: ["pausedUP", "stalledUP"]
    actions:
      - type: force_start
```

---

## API Specification

### Base URL

```
http://localhost:5000/api
```

### Authentication

All endpoints require API key authentication via:
- **Query parameter**: `?key=your-api-key`
- **Header**: `X-API-Key: your-api-key`

Returns `401 Unauthorized` if missing or invalid.

### Endpoints

#### Execute Rules (Queue Job)

**Request:**
```http
POST /api/execute?context=scheduled&hash=abc123&key=xxx
```

**Query Parameters:**
- `context` (optional): Context filter (scheduled, on_added, on_completed, etc.)
- `hash` (optional): Torrent hash filter (process single torrent)
- `key` (required): API key

**Response:** `202 Accepted`
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "context": "scheduled",
  "hash": "abc123",
  "queued_at": "2025-12-13T10:00:00Z"
}
```

---

#### Get Job Status

**Request:**
```http
GET /api/jobs/550e8400-e29b-41d4-a716-446655440000?key=xxx
```

**Response:** `200 OK`
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "context": "scheduled",
  "hash": null,
  "created_at": "2025-12-13T10:00:00Z",
  "started_at": "2025-12-13T10:00:01Z",
  "completed_at": "2025-12-13T10:00:05Z",
  "result": {
    "torrents_processed": 15,
    "rules_matched": 3,
    "actions_executed": 5
  },
  "error": null
}
```

**Status Values:**
- `pending` - Job queued, not started
- `processing` - Job currently executing
- `completed` - Job finished successfully
- `failed` - Job failed with error
- `cancelled` - Job was cancelled

---

#### List Jobs

**Request:**
```http
GET /api/jobs?status=completed&context=scheduled&limit=20&offset=0&key=xxx
```

**Query Parameters:**
- `status` (optional): Filter by status (pending, processing, completed, failed, cancelled)
- `context` (optional): Filter by context
- `limit` (optional): Number of jobs to return (default: 50, max: 100)
- `offset` (optional): Pagination offset (default: 0)
- `key` (required): API key

**Response:** `200 OK`
```json
{
  "total": 150,
  "limit": 20,
  "offset": 0,
  "jobs": [
    {
      "job_id": "...",
      "status": "completed",
      "context": "scheduled",
      "created_at": "2025-12-13T10:00:00Z",
      "completed_at": "2025-12-13T10:00:05Z"
    },
    ...
  ]
}
```

---

#### Cancel Job

**Request:**
```http
DELETE /api/jobs/550e8400-e29b-41d4-a716-446655440000?key=xxx
```

**Response:** `200 OK`
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "cancelled",
  "message": "Job cancelled successfully"
}
```

**Error Response:** `400 Bad Request`
```json
{
  "error": "Cannot cancel job in status: processing"
}
```

*Note: Only jobs with status `pending` can be cancelled*

---

#### Health Check

**Request:**
```http
GET /api/health
```

*Note: Health check does NOT require authentication*

**Response:** `200 OK`
```json
{
  "status": "healthy",
  "version": "0.4.0",
  "queue": {
    "backend": "sqlite",
    "pending_jobs": 5,
    "processing_jobs": 1
  },
  "worker": {
    "status": "running",
    "last_job_completed": "2025-12-13T10:00:05Z"
  },
  "qbittorrent": {
    "connected": true,
    "version": "v5.0.2"
  }
}
```

**Unhealthy Response:** `503 Service Unavailable`
```json
{
  "status": "unhealthy",
  "errors": [
    "Worker thread not responding",
    "Cannot connect to qBittorrent"
  ]
}
```

---

#### Server Statistics

**Request:**
```http
GET /api/stats?key=xxx
```

**Response:** `200 OK`
```json
{
  "jobs": {
    "total": 1500,
    "pending": 5,
    "processing": 1,
    "completed": 1450,
    "failed": 40,
    "cancelled": 4
  },
  "performance": {
    "average_execution_time": "4.2s",
    "jobs_per_hour": 12.5
  },
  "queue": {
    "backend": "sqlite",
    "depth": 6
  },
  "uptime": "5d 12h 30m"
}
```

---

#### Version Information

**Request:**
```http
GET /api/version
```

*Note: Version endpoint does NOT require authentication*

**Response:** `200 OK`
```json
{
  "version": "0.4.0",
  "api_version": "1.0",
  "qbittorrent_api_version": "2024.12.0",
  "build_date": "2025-12-13",
  "git_commit": "abc123def456"
}
```

---

### Error Responses

**401 Unauthorized** - Missing or invalid API key
```json
{
  "error": "Unauthorized",
  "message": "Invalid or missing API key"
}
```

**404 Not Found** - Job not found
```json
{
  "error": "Not Found",
  "message": "Job not found: 550e8400-e29b-41d4-a716-446655440000"
}
```

**500 Internal Server Error** - Server error
```json
{
  "error": "Internal Server Error",
  "message": "An unexpected error occurred",
  "trace_id": "abc-123-def"
}
```

---

## Database Schemas

### SQLite Schema

**File**: `/config/qbt-rules.db`

```sql
-- Jobs table: Complete job data
CREATE TABLE jobs (
    id TEXT PRIMARY KEY,  -- UUID
    context TEXT,         -- Context filter (scheduled, on_added, etc.)
    hash TEXT,            -- Optional torrent hash filter
    status TEXT NOT NULL, -- pending, processing, completed, failed, cancelled
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    result TEXT,          -- JSON serialized result
    error TEXT,           -- Error message if failed
    INDEX idx_status (status),
    INDEX idx_created_at (created_at),
    INDEX idx_context (context)
);

-- Queue table: Pending jobs only (ordered processing)
CREATE TABLE queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL UNIQUE,
    priority INTEGER DEFAULT 0,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

-- Schema version tracking
CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO schema_version (version) VALUES (1);
```

**Migration Strategy:**
- Auto-detect schema version on startup
- Apply migrations sequentially
- No data loss between versions

---

### Redis Schema

**Connection**: Configured via `QBT_RULES_QUEUE_REDIS_URL`

**Data Structures:**

```
# Queue: Ordered list of pending job IDs
LIST: qbt_rules:queue:pending
  -> [job_id_1, job_id_2, job_id_3]

# Job Data: Hash per job
HASH: qbt_rules:jobs:{job_id}
  -> {
       "id": "uuid",
       "context": "scheduled",
       "hash": null,
       "status": "pending",
       "created_at": "2025-12-13T10:00:00Z",
       "started_at": null,
       "completed_at": null,
       "result": null,
       "error": null
     }

# Job Index by Status: Set per status
SET: qbt_rules:jobs:status:{status}
  -> {job_id_1, job_id_2, ...}

# Job Index by Context: Set per context
SET: qbt_rules:jobs:context:{context}
  -> {job_id_1, job_id_2, ...}

# Time-sorted jobs: Sorted set for cleanup
ZSET: qbt_rules:jobs:by_time
  -> {job_id: timestamp}
```

**Key Patterns:**
- `qbt_rules:queue:pending` - Pending job queue (LIST)
- `qbt_rules:jobs:{id}` - Job data (HASH)
- `qbt_rules:jobs:status:{status}` - Jobs by status (SET)
- `qbt_rules:jobs:context:{context}` - Jobs by context (SET)
- `qbt_rules:jobs:by_time` - Jobs sorted by created_at (ZSET)

**Cleanup Strategy:**
- Use ZSET `qbt_rules:jobs:by_time` to find jobs older than retention period
- Delete job data and remove from all indexes

---

## Implementation Phases

### Phase 0: Planning ✅

**Deliverable**: This document (PLAN.md)

**Tasks**:
- [x] Document architecture
- [x] Design API specification
- [x] Define database schemas
- [x] Create configuration reference
- [x] Outline implementation phases

---

### Phase 1: Configuration System Refactor

**Deliverable**: Universal config resolver with _FILE support

**Files**:
- `src/qbt_rules/config.py`

**Tasks**:
1. Implement `resolve_config()` function
   - CLI flag precedence
   - `{VAR}_FILE` variant support
   - Direct environment variable
   - Config file with dot-notation
   - Default value fallback

2. Implement `get_nested_config()` helper
   - Parse dot-notation keys (e.g., `server.port`)
   - Navigate nested dictionaries

3. Type conversion helpers
   - `parse_duration()` for time values (7d, 30 days, etc.)
   - `parse_bool()` for boolean strings
   - `parse_int()` for integer strings

4. Create constant mapping
   ```python
   ENV_VARS = {
       'server.host': 'QBT_RULES_SERVER_HOST',
       'server.port': 'QBT_RULES_SERVER_PORT',
       # ... all settings
   }
   ```

5. Update `config/config.example.yml`
   - New structure with all sections
   - Document all settings with comments
   - Include Docker-specific defaults

**Testing**:
- Test _FILE variant resolution
- Test precedence order
- Test type conversions
- Test missing file handling

**Dependencies**: None

---

### Phase 2: Queue System

**Deliverable**: Queue manager interface and SQLite backend

**Files**:
- `src/qbt_rules/queue_manager.py`
- `src/qbt_rules/queue_backends/__init__.py`
- `src/qbt_rules/queue_backends/sqlite_queue.py`

**Tasks**:

1. **Queue Manager Interface** (`queue_manager.py`):
   ```python
   class QueueManager(ABC):
       @abstractmethod
       def enqueue(self, context, hash=None) -> str:
           """Add job to queue, return job ID"""

       @abstractmethod
       def dequeue(self) -> Optional[Dict]:
           """Get next job from queue"""

       @abstractmethod
       def get_job(self, job_id: str) -> Optional[Dict]:
           """Get job by ID"""

       @abstractmethod
       def list_jobs(self, status=None, context=None, limit=50, offset=0) -> List[Dict]:
           """List jobs with filtering"""

       @abstractmethod
       def update_status(self, job_id: str, status: str, **kwargs):
           """Update job status and optional fields"""

       @abstractmethod
       def cancel_job(self, job_id: str) -> bool:
           """Cancel pending job"""

       @abstractmethod
       def cleanup_old_jobs(self, retention_period: str):
           """Remove old completed/failed jobs"""
   ```

2. **SQLite Backend** (`queue_backends/sqlite_queue.py`):
   - Create tables on initialization
   - Thread-safe operations with connection per thread
   - Implement all QueueManager methods
   - Schema migration support
   - Proper indexes for performance

3. **Queue Factory**:
   ```python
   def create_queue(backend='sqlite', **kwargs) -> QueueManager:
       if backend == 'sqlite':
           return SQLiteQueue(**kwargs)
       elif backend == 'redis':
           return RedisQueue(**kwargs)
       raise ValueError(f"Unknown backend: {backend}")
   ```

**Testing**:
- Test job creation and retrieval
- Test queue ordering (FIFO)
- Test status updates
- Test job cancellation
- Test cleanup logic
- Test concurrent access (multi-threading)

**Dependencies**: Phase 1 (config system)

---

### Phase 3: Worker Process

**Deliverable**: Background worker consuming queue and executing jobs

**Files**:
- `src/qbt_rules/worker.py`

**Tasks**:

1. **Worker Class**:
   ```python
   class Worker:
       def __init__(self, queue: QueueManager, api_client, rules, config):
           self.queue = queue
           self.api_client = api_client
           self.rules = rules
           self.config = config
           self.running = False
           self.thread = None

       def start(self):
           """Start worker thread"""

       def stop(self):
           """Graceful shutdown"""

       def run(self):
           """Main worker loop"""

       def process_job(self, job):
           """Execute single job"""
   ```

2. **Job Processing Logic**:
   - Dequeue job from queue
   - Update status to "processing"
   - Create RulesEngine with context filter
   - Execute rules (with error handling)
   - Update job with result or error
   - Mark as completed/failed

3. **Error Handling**:
   - Catch all exceptions
   - Store full traceback in job error field
   - Log errors with trace ID
   - Continue processing next job

4. **Graceful Shutdown**:
   - Stop dequeuing new jobs
   - Wait for current job to complete
   - Set timeout for forced shutdown

**Testing**:
- Test job execution end-to-end
- Test error handling
- Test graceful shutdown
- Test thread safety

**Dependencies**: Phase 2 (queue system)

---

### Phase 4: HTTP API Server

**Deliverable**: Flask application with all endpoints

**Files**:
- `src/qbt_rules/server.py`

**Tasks**:

1. **Flask Application Setup**:
   - Initialize Flask app
   - Configure logging
   - Set up error handlers

2. **Authentication Middleware**:
   ```python
   @app.before_request
   def authenticate():
       api_key = request.args.get('key') or request.headers.get('X-API-Key')
       expected_key = config['server']['api_key']
       if not secrets.compare_digest(api_key or '', expected_key):
           return jsonify({"error": "Unauthorized"}), 401
   ```

3. **Implement All Endpoints**:
   - POST `/api/execute` - Queue job
   - GET `/api/jobs` - List jobs
   - GET `/api/jobs/{id}` - Get job status
   - DELETE `/api/jobs/{id}` - Cancel job
   - GET `/api/health` - Health check (no auth)
   - GET `/api/stats` - Statistics
   - GET `/api/version` - Version info (no auth)

4. **Gunicorn Integration**:
   ```python
   def run_server(host, port, workers):
       from gunicorn.app.base import BaseApplication

       class StandaloneApplication(BaseApplication):
           def __init__(self, app, options=None):
               self.application = app
               self.options = options or {}
               super().__init__()

           def load_config(self):
               for key, value in self.options.items():
                   self.cfg.set(key, value)

           def load(self):
               return self.application

       options = {
           'bind': f'{host}:{port}',
           'workers': workers,
           'worker_class': 'sync',
           'timeout': 120,
       }

       StandaloneApplication(app, options).run()
   ```

**Testing**:
- Test all endpoints with various inputs
- Test authentication (valid, invalid, missing)
- Test error responses
- Load testing with concurrent requests

**Dependencies**: Phase 2 (queue system), Phase 3 (worker)

---

### Phase 5: CLI Refactor

**Deliverable**: CLI as HTTP client with --serve mode

**Files**:
- `src/qbt_rules/cli.py`

**Tasks**:

1. **Add All CLI Flags**:
   - Server flags: `--server-host`, `--server-port`, `--server-api-key`, `--server-workers`
   - Client flags: `--client-server-url`, `--client-api-key`
   - Queue flags: `--queue-backend`, `--queue-sqlite-path`, `--queue-redis-url`, `--queue-cleanup-after`
   - qBittorrent flags: `--qbittorrent-host`, `--qbittorrent-username`, `--qbittorrent-password`
   - Execution flags: `--context`, `--hash`, `--dry-run`, `--trace`
   - Mode flags: `--serve`, `--wait`
   - Job management: `--list-jobs`, `--job-status <id>`, `--cancel-job <id>`, `--stats`

2. **Server Mode** (`--serve`):
   ```python
   if args.serve:
       queue = create_queue(backend, **queue_config)
       worker = Worker(queue, api_client, rules, config)
       worker.start()
       run_server(host, port, workers)
   ```

3. **Client Mode** (default):
   ```python
   def execute_via_api(server_url, api_key, context, hash):
       response = requests.post(
           f"{server_url}/api/execute",
           params={'context': context, 'hash': hash, 'key': api_key}
       )
       job = response.json()
       print(f"✓ Job queued: {job['job_id']}")

       if args.wait:
           poll_until_complete(server_url, api_key, job['job_id'])
   ```

4. **Job Management Commands**:
   - `--list-jobs`: Pretty-print table of jobs
   - `--job-status <id>`: Show detailed job info
   - `--cancel-job <id>`: Cancel pending job
   - `--stats`: Show server statistics

**Testing**:
- Test server startup
- Test client job submission
- Test --wait polling
- Test all job management commands

**Dependencies**: Phase 4 (HTTP server)

---

### Phase 6: qbittorrent-api Migration

**Deliverable**: Wrapper maintaining same interface

**Files**:
- `src/qbt_rules/api.py`
- `pyproject.toml`

**Tasks**:

1. **Update Dependencies**:
   ```toml
   dependencies = [
       "requests>=2.31.0",
       "PyYAML>=6.0.2",
       "qbittorrent-api>=2024.12.0",  # NEW
   ]
   ```

2. **Refactor QBittorrentAPI Class**:
   ```python
   import qbittorrentapi

   class QBittorrentAPI:
       def __init__(self, host: str, username: str, password: str):
           self.client = qbittorrentapi.Client(
               host=host,
               username=username,
               password=password
           )

       def get_torrents(self, filter_type=None, category=None, tag=None):
           return self.client.torrents_info(
               filter=filter_type,
               category=category,
               tag=tag
           )

       def get_properties(self, torrent_hash: str):
           return self.client.torrents_properties(torrent_hash=torrent_hash)

       # ... map all other methods
   ```

3. **Test Data Compatibility**:
   - Verify all fields accessible in rules still work
   - Test with different qBittorrent versions (v4.x, v5.x)
   - Ensure no breaking changes in field access

**Testing**:
- Integration tests with real qBittorrent instance
- Test multi-version compatibility
- Test all API methods

**Dependencies**: None (can be parallel with other phases)

---

### Phase 7: Redis Queue Backend

**Deliverable**: Optional high-performance queue backend

**Files**:
- `src/qbt_rules/queue_backends/redis_queue.py`
- `pyproject.toml`

**Tasks**:

1. **Update Dependencies**:
   ```toml
   [project.optional-dependencies]
   redis = ["redis>=5.0.0"]
   ```

2. **Implement RedisQueue**:
   - Implement all QueueManager methods
   - Use Redis data structures (LIST, HASH, SET, ZSET)
   - Connection pooling
   - Retry logic for transient failures

3. **Configuration**:
   - Add `QBT_RULES_QUEUE_REDIS_URL` support
   - Document Redis deployment patterns

**Testing**:
- Test all queue operations
- Test connection failure handling
- Test data persistence
- Performance benchmarks vs SQLite

**Dependencies**: Phase 2 (queue interface)

---

### Phase 8: Terminology Migration

**Deliverable**: All "trigger" references become "context"

**Files**:
- `src/qbt_rules/engine.py`
- `src/qbt_rules/cli.py`
- `config/rules.example.yml`
- `config/config.example.yml`
- All test files
- All documentation

**Tasks**:

1. **Code Updates**:
   - Search and replace "trigger" → "context"
   - Update variable names: `trigger_filter` → `context_filter`
   - Update function parameters
   - Update docstrings

2. **Configuration Updates**:
   - Update example rules to use `context:`
   - Update config comments
   - Update README examples

3. **Documentation Updates**:
   - Update all documentation
   - Update Wiki pages (separate repo)

**Testing**:
- Verify all existing tests pass
- Add tests for context filtering
- Test backward compatibility if needed

**Dependencies**: Can be done at any point, preferably after core functionality

---

### Phase 9: Docker Infrastructure

**Deliverable**: Dockerfile, docker-compose examples, GitHub Actions

**Files**:
- `Dockerfile`
- `.dockerignore`
- `examples/docker-compose/minimal.yml`
- `examples/docker-compose/full-stack.yml`
- `examples/docker-compose/with-redis.yml`
- `.github/workflows/docker.yml`

**Tasks**:

1. **Create Dockerfile** (see PLAN.md architecture section for full dockerfile)

2. **Create .dockerignore**:
   ```
   **/__pycache__
   **/*.pyc
   **/.pytest_cache
   .git
   .github
   tests/
   docs/
   *.md
   !README.md
   .env
   config/*.yml
   !config/*.example.yml
   ```

3. **Create Docker Compose Examples**:
   - Minimal: qbt-rules server only
   - Full-stack: qBittorrent + qbt-rules + secrets
   - With Redis: Full stack + Redis backend

4. **GitHub Actions Workflow**:
   - Trigger on tag push (v*)
   - Multi-arch build (amd64, arm64, armv7)
   - Push to ghcr.io
   - Tag: latest, {version}, {major.minor}

**Testing**:
- Build image locally
- Test all docker-compose examples
- Test multi-arch builds
- Test GitHub Actions workflow

**Dependencies**: All core functionality must be complete

---

### Phase 10: Documentation

**Deliverable**: Complete documentation suite

**Files**:
- `docs/Architecture.md`
- `docs/API.md`
- `docs/Docker.md`
- `README.md` (updates)
- `CHANGELOG.md` (updates)

**Tasks**:

1. **Architecture.md**:
   - Component diagram
   - Data flow diagrams
   - Queue system explanation
   - Worker process logic
   - Security considerations

2. **API.md**:
   - Complete endpoint reference
   - Request/response examples
   - Authentication guide
   - Error handling
   - Rate limiting (future)

3. **Docker.md**:
   - Installation guide
   - Docker Compose setup
   - Environment variable reference
   - Secret management
   - Volume management
   - Troubleshooting

4. **README.md Updates**:
   - Change to Docker-first installation
   - Remove PyPI instructions
   - Update all examples with "context" terminology
   - Link to new documentation

5. **CHANGELOG.md**:
   - Document all breaking changes
   - List new features
   - Migration guide (minimal since single user)

**Testing**:
- Follow docs as new user would
- Test all examples
- Verify all links work

**Dependencies**: All implementation complete

---

### Phase 11: Testing

**Deliverable**: Comprehensive test suite

**Files**:
- `tests/test_queue_sqlite.py`
- `tests/test_queue_redis.py`
- `tests/test_worker.py`
- `tests/test_server.py`
- `tests/test_client.py`
- `tests/test_config.py`
- `tests/integration/test_end_to_end.py`

**Tasks**:

1. **Unit Tests**:
   - Config resolution (including _FILE)
   - Queue backends (SQLite, Redis)
   - Worker job processing
   - API authentication
   - qbittorrent-api wrapper

2. **Integration Tests**:
   - Client → Server → Queue → Worker → RulesEngine
   - Full job lifecycle
   - Concurrent requests
   - Error scenarios

3. **Docker Tests**:
   - Container builds
   - Health check functionality
   - Volume persistence
   - Multi-container networking

**Testing**:
- Achieve >90% code coverage
- Test all error paths
- Test edge cases

**Dependencies**: All implementation complete

---

### Phase 12: Release Preparation

**Deliverable**: Ready for v0.4.0 release

**Files**:
- `pyproject.toml`
- `src/qbt_rules/__version__.py`
- `CHANGELOG.md`
- `.github/workflows/release.yml`

**Tasks**:

1. **Update Version**:
   - Set version to `0.4.0` in `pyproject.toml`
   - Update `__version__.py`

2. **Update Release Workflow**:
   - Remove PyPI publishing steps
   - Keep GitHub release creation
   - Add Docker image build trigger

3. **Final CHANGELOG**:
   - Complete all sections
   - Document breaking changes clearly
   - Include migration notes

4. **Tag Release**:
   ```bash
   git tag -a v0.4.0 -m "Release v0.4.0: Client-server architecture"
   git push origin v0.4.0
   ```

**Testing**:
- Test release workflow in staging
- Verify Docker images build correctly
- Test installation from Docker

**Dependencies**: All previous phases complete

---

## Testing Strategy

### Unit Testing

**Coverage Goal**: >90%

**Areas**:
- Configuration resolution
- Queue operations (both backends)
- Worker job processing
- API endpoint handlers
- Authentication middleware
- Error handling

**Tools**:
- pytest
- pytest-cov
- pytest-mock

---

### Integration Testing

**Scenarios**:
1. **Full Job Lifecycle**:
   - Client submits job → queued → worker processes → result stored
   - Verify status transitions
   - Verify result data

2. **Concurrent Execution**:
   - Multiple clients submit jobs simultaneously
   - Verify no race conditions
   - Verify queue ordering

3. **Error Scenarios**:
   - qBittorrent connection failure
   - Invalid rules syntax
   - Queue backend failure

4. **Container Integration**:
   - Multi-container Docker Compose setup
   - qBittorrent → webhook → qbt-rules
   - Volume persistence across restarts

---

### Performance Testing

**Benchmarks**:
- Job throughput (jobs/second)
- Queue latency (time from submit to start)
- API response times
- Memory usage under load

**Load Testing**:
- 100 concurrent webhook requests
- 1000 jobs in queue
- 24-hour continuous operation

---

### Security Testing

**Areas**:
- API key authentication
- Timing attack resistance (constant-time comparison)
- SQL injection (parameterized queries)
- File path traversal (_FILE variant)
- Docker container security (non-root user)

---

## Success Criteria

### Functional Requirements

- ✅ Server starts and accepts API requests
- ✅ CLI submits jobs via HTTP API
- ✅ Jobs execute through queue sequentially
- ✅ SQLite queue persists across restarts
- ✅ Redis queue works (optional)
- ✅ All existing rules work with "context" terminology
- ✅ qbittorrent-api provides same data as direct API
- ✅ Webhook integration works (qBittorrent → qbt-rules)
- ✅ Docker container runs with proper permissions
- ✅ Health check endpoint functional
- ✅ Job management commands work

### Non-Functional Requirements

- ✅ Response time <100ms for API requests (excluding job execution)
- ✅ Queue throughput >10 jobs/second
- ✅ Memory usage <512MB under normal load
- ✅ Zero data loss on server restart
- ✅ Graceful shutdown within 30 seconds
- ✅ Test coverage >90%

### Documentation Requirements

- ✅ Complete API reference
- ✅ Docker deployment guide
- ✅ Environment variable reference
- ✅ Troubleshooting guide
- ✅ Migration notes for v0.3.x users

### Release Requirements

- ✅ Docker images for amd64, arm64, armv7
- ✅ GitHub Container Registry publishing
- ✅ All tests pass
- ✅ Documentation complete
- ✅ CHANGELOG updated
- ✅ Example docker-compose files tested

---

## Cross-Seeding Planning

**Status**: Architecture design only (implementation deferred)

### Integration Patterns

1. **cross-seed Webhook → qbt-rules**:
   ```
   cross-seed detects match → webhook to qbt-rules
   → POST /api/execute?context=cross_seed&hash={hash}
   → Rule processes torrent
   ```

2. **Directory Monitoring**:
   ```
   cross-seed outputs .torrent files → directory
   → qbt-rules monitors directory
   → Adds torrents with category/tags
   ```

3. **Direct API Integration** (future):
   ```
   qbt-rules → cross-seed API
   → Query for potential matches
   → Automatic cross-seed setup
   ```

### Configuration Schema

```yaml
cross_seeding:
  enabled: false
  mode: webhook  # webhook, directory, api

  # Webhook mode
  webhook:
    context: cross_seed

  # Directory mode
  directory:
    path: /watch/cross-seed
    poll_interval: 60

  # Tracker mapping
  trackers:
    - name: tracker1
      url_pattern: 'tracker1.example.com'
      category_prefix: 'CS-'
      auto_add: true
    - name: tracker2
      url_pattern: 'tracker2.example.com'
      category_prefix: 'CS-'
      auto_add: false
```

### Future Actions

```yaml
# Add torrent from cross-seed match
- type: add_cross_seed
  params:
    torrent_file: /path/to/match.torrent
    tracker: tracker1
    category_prefix: true
    paused: true

# Match existing torrent for cross-seeding
- type: match_cross_seed
  params:
    trackers: [tracker1, tracker2]
    auto_add: true
```

### API Endpoints (Future)

```
POST /api/cross-seed/match?hash={hash}&tracker={name}
GET  /api/cross-seed/status/{job_id}
```

**Phase 1 Deliverable**: Documentation only

---

## v0.6.0 Planning

**Status**: In progress. Nine initiatives, all confirmed in scope for a single v0.6.0 release (not staged across multiple minors). Initiatives 6 (Prometheus metrics) and 7 (legacy cleanup, including the `keep_files` removal originally scoped for v0.7.0) were both folded in here since nothing had been tagged/released yet — no reason to split either into a separate cycle. Initiative 8 (the `_LOG`/`_LOGGING` env var fix) surfaced during Initiative 7's legacy audit as the same bug shape found for `qbittorrent.*`, applied to `logging.*`. Initiative 9 is a follow-up architecture review of the `get_*_config()` pattern itself, which found (and fixed) one more instance of the same bug for `engine.dry_run`.

### 1. `delete_torrent`: `keep_files` → `delete_files` rename

**Status**: Implemented.

`delete_torrent` was the only action with inverted-boolean semantics (`keep_files: true` meant *don't* delete) — every other parameterized action (`category`, `tags`, `limit`) is named directly. `delete_files` is now the canonical parameter, matching `api.py`'s own `delete_torrents(hashes, delete_files: bool)` vocabulary and removing the inversion rather than adding one.

```yaml
actions:
  - type: delete_torrent
    params:
      delete_files: true   # canonical; also the default if params are omitted
```

**Update:** `keep_files` was fully removed (not just deprecated) later in this same v0.6.0 cycle — see Initiative 7 below. Since v0.6.0 hadn't shipped yet, nobody ever saw a released version where it worked *and* was deprecated, so there was no two-release migration to preserve.

### 2. Internal cron scheduler

**Status**: Implemented. Multi-worker fork safety verified empirically (real 2-worker server, 2 minute boundaries crossed, exactly 2 jobs enqueued).

Replaces reliance on an external cron/systemd timer/sidecar container hitting `/api/execute?context=X` on a schedule. New `Scheduler` class (`src/qbt_rules/scheduler.py`), structurally parallel to `Worker` — own thread, `start()`/`stop()` lifecycle — reading a new `schedule:` list from `config.yml` and calling `queue.enqueue(context=...)` directly on each cron fire (`queue_manager.enqueue()` has no Flask coupling, confirmed safe to call from a non-request context).

```yaml
schedule:
  - cron: "*/30 * * * *"
    context: cron
  - cron: "0 3 * * *"
    context: nightly
```

Dependency: `croniter` (new core dependency — chosen over APScheduler, which brings a competing concurrency model into a codebase that already has exactly one thread-per-component pattern, and doesn't solve the multi-worker duplication problem below for free anyway).

**Gunicorn multi-worker safety**: `run_server()` uses `preload_app: True` with a `post_fork` hook that restarts `Worker`'s thread in each forked child (threads don't survive `fork()`). The scheduler is started *before* Gunicorn forks (in `run_server_mode()`, same place `worker.start()` is called) and is deliberately **not** added to `post_fork` — so it runs exactly once, in the master/arbiter process, regardless of `server.workers` count. Must be confirmed with a real `workers=2` smoke test before merge, not just unit-mocked.

Regression test case: the malware-incident fix (see BUGS.md) relies on an external 30-minute cron hitting `context=cron` — the internal scheduler must be able to fully replace that external job.

### 3. Generic outbound notification action

**Status**: Implemented.

New `notify` action, single type with a `service` selector (`discord`/`slack`/`ntfy`/`generic`) rather than three near-duplicate actions, since each service wants a different payload shape:

```yaml
- type: notify
  params:
    service: discord
    url: "https://discord.com/api/webhooks/..."   # optional if notifications.webhook_url is set
    message: "Torrent {name} matched rule, ratio {ratio}, tags: {tags}"
```

New `notifications:` config section (`webhook_url` with `_FILE` secret support, `service`). `ActionExecutor` does **not** hold a `Config` reference — `_FILE` resolution only happens via `cli.py`'s `resolve_config()`, which needs CLI `args` that `ActionExecutor` never has. Instead, `get_notifications_config(args, config_obj)` resolves the webhook URL/service once at server startup (same place `server_config`/`schedule_entries` already are) and threads the plain resolved dict down through `Worker` → `RulesEngine` → `ActionExecutor` as an optional `notifications_config` param. Always-fire, no idempotency tracking (matches `reannounce`/`recheck`); accepted risk that a rule re-evaluated across multiple contexts will re-notify — documented, with the `add_tag` + condition-exclusion workaround. `{tags}` in message templates is cleaned up via `parse_tags()` rather than exposing the raw comma-separated API string. Confirmed via a real end-to-end test (not mocked) that `notify` placed after `delete_torrent` in the same rule still renders the correct torrent name.

### 4. Sonarr/Radarr blocklist-and-research action

**Status**: Implemented. Overseerr explicitly deferred (it's a request-management frontend over Sonarr/Radarr, not an independent download queue with its own retry primitive — the underlying need is already covered once this action exists).

New `arr_blocklist` action (`params.service: sonarr|radarr`, required) — for the concrete case of a torrent qbt-rules just deleted for being bad/stalled, correlate it to the Sonarr/Radarr queue via `GET /api/v3/queue` (paginated, matching `downloadId` to the uppercased torrent hash — collecting **every** matching record, since a season-pack download can produce multiple queue records sharing the same `downloadId`), then `DELETE /api/v3/queue/{id}?removeFromClient=false&blocklist=true` for each match, followed by one combined `POST /api/v3/command` (`EpisodeSearch`/`MoviesSearch`, covering all matched episodes/movies) to trigger a replacement search — unless `params.search: false`, in which case blocklisting still happens but no search is triggered (default `search: true`). `removeFromClient` defaults `false` since a preceding `delete_torrent` action in the same rule already removed it from qBittorrent — `remove_from_client: true` overrides it, documented prominently for standalone use. No queue match is a non-fatal skip (logs a warning, returns success) rather than an error, since most torrents aren't arr-managed.

New `integrations:` config section (`integrations.sonarr.url`/`.api_key`, `integrations.radarr.*`, `_FILE` secret support identical to `qbittorrent.password`). Threading follows the same pattern `notify` uses (see Initiative 3): `get_integrations_config(args, config_obj)` in `cli.py` calls the config-architecture cleanup's `resolve_section_config()` helper once per service (`integrations.sonarr`, `integrations.radarr` — dotted nested section names, no `ENV_VAR_MAP` entries needed at all), resolved once at startup, threaded down through `Worker` → `RulesEngine` → `ActionExecutor` as its own optional `integrations_config` param alongside `notifications_config`.

### 5. Read-only web dashboard

**Status**: Implemented.

First web UI — 100% greenfield (no prior templates/static serving/Jinja2 usage anywhere in `server.py`). Server-rendered via Flask + Jinja2 (no new frontend framework/build pipeline), reusing data the JSON API already exposes, no new query logic:

- `GET /dashboard` — worker/queue status + job counts by status, version
- `GET /dashboard/jobs` (paginated, `?status=` filter), `GET /dashboard/jobs/<job_id>` — job list/detail
- `GET /dashboard/rules` — read-only, sourced from the already hot-reload-aware `config_obj.get_rules()`

`create_app()` gained an optional 4th `config: Optional[Config] = None` param (stored as the module-level `dashboard_config` global) for the rules view — optional so every pre-existing 3-arg call site keeps working unchanged; `/dashboard/rules` reports itself unavailable if `config` wasn't provided rather than erroring. `cli.py`'s `run_server_mode()` passes `config=config_obj`.

Auth: reuses the existing `require_api_key` decorator (same `?key=` query param the JSON API already supports) rather than building a login form — accepted trade-off for a read-only, home-lab-scale v0.6 dashboard. Every internal link carries `?key=` forward so navigation stays authenticated. `FilteredLogger.access()` (Gunicorn access log filter) now also suppresses `/dashboard*` paths by default, alongside the pre-existing `/api/health` suppression, since a browsing session generates far more key-bearing URLs than a scripted API client typically would.

**Packaging risk — verified fixed**: `pyproject.toml`'s `package-data` now includes `"templates/*.html"` (was only `py.typed`). Confirmed via `python -m build --wheel` + a clean-venv install that all 5 template files land in the installed package — not just a code-review note, actually built and checked before merge.

Templates: `base.html` (nav + shared styling, light/dark via `prefers-color-scheme`) plus one template per page (`dashboard.html`, `jobs.html`, `job_detail.html`, `rules.html`), all under `src/qbt_rules/templates/` — Flask's default `template_folder` resolution (relative to `server.py`'s package) needed no explicit override.

Tested against a real running server (not just unit-mocked): submitted a real job through `/api/execute`, confirmed it appeared correctly in `/dashboard/jobs` and rendered its result in `/dashboard/jobs/<id>`; confirmed 401 without a key and the rules page rendering real `rules.yml` content.

**Update (dark UI rewrite + route/auth revisit)**: The dashboard was moved off the `/dashboard/*` prefix to the site root -- `/`, `/jobs`, `/jobs/<job_id>`, `/rules` -- to read as the app's home surface rather than a sub-section; `/api/*` and `/metrics` are untouched. `url_for()` uses endpoint names, not literal paths, so no template `url_for(...)` call sites needed to change, only the `@app.route(...)` strings themselves. The "accepted trade-off" above (raw `?key=` auth, no login form) was revisited: dashboard routes now use a new `require_api_key_dashboard` decorator that redirects a human to `/login` (carrying the original destination through as `?next=`, parsed back down to a same-origin path + preserved query params -- never used as a raw redirect target, so a crafted `next` can't send anyone off-site) instead of the JSON API's raw 401. `/login` itself is unauthenticated (can't require a key to reach the page that lets you enter one) and its form re-submits via GET straight to the original destination, so no session/cookie state was introduced. `require_api_key` (JSON 401 behavior) is unchanged and still used by every `/api/*` route and `/metrics`. `FilteredLogger`'s dashboard-path suppression was updated from a `/dashboard` prefix check to an explicit allowlist (`/`, `/jobs`, `/rules`, `/login`) so unrelated 404 probes don't get swept in by an accidental broad match. Visual rewrite (dark theme, richer stat tiles, per-rule condition-tree view, resolved-YAML detail panel) done in the same pass -- see `ui/demo-*.html` for the concept work this was based on.

### 6. Prometheus metrics support

**Status**: Implemented.

New optional `GET /metrics` endpoint (`server.py`), off by default (`metrics.enabled: false`), `prometheus_client` as a new `metrics` optional extra (`pip install qbt-rules[metrics]`) rather than a core dependency — mirrors the existing `redis` extra precedent. `/metrics` requires the API key like every route except `/api/health`/`/api/version`.

**Fork-safety** was the central design problem, directly parallel to how `scheduler.py` (Initiative 2, above) already solved the same category of issue: Gunicorn's `preload_app` + fork model forks a naive in-process counter into `server.workers` independent, unsynchronized copies. Solved via `prometheus_client`'s multiprocess mode — `PROMETHEUS_MULTIPROC_DIR` (the library-mandated env var name) set in `cli.py` from the resolved `metrics.multiproc_dir` config, right before the deferred `import qbt_rules.metrics` (must happen before prometheus_client's own first import anywhere in the process, since it resolves its value-storage strategy exactly once at that point); stale files cleared at master startup, before Gunicorn forks; a new `child_exit` Gunicorn hook alongside the existing `post_fork`. **Verified empirically** with a real 2-worker server (not just reasoned about): HTTP request and job counts correctly summed across the master process and both forked workers; killing a worker mid-run and letting Gunicorn respawn a replacement didn't lose or double-count anything.

**Hybrid metric design** — new `src/qbt_rules/metrics.py`:
- Real Counters/Histograms (need multiprocess mode, since nothing else durably tracks these): `qbt_rules_http_requests_total`/`_duration_seconds`, `qbt_rules_actions_executed_total` (wraps `ActionExecutor.execute()`, labeled by `action_type` only — no rule-name label, to avoid unbounded cardinality from free-form rule names), `qbt_rules_job_duration_seconds`, `qbt_rules_scheduler_fires_total`.
- On-demand gauges, computed fresh on every scrape from data already exposed by `queue.get_stats()`/`get_queue_depth()`/`worker.get_status()` (no new instrumentation call sites needed in either queue backend, which share no common chokepoint to instrument at write time): `qbt_rules_queue_depth`, `qbt_rules_jobs_total`, `qbt_rules_worker_running`, `qbt_rules_worker_last_job_completed_timestamp_seconds`, `qbt_rules_scheduler_entries`.

`metrics.py`'s module-level functions (`record_*()`) are safe to call unconditionally from `engine.py`/`worker.py`/`scheduler.py` regardless of whether metrics are enabled or `prometheus_client` is even installed — they silently no-op until `metrics.init(enabled=True)` has run, and `prometheus_client` itself is never imported at `metrics.py`'s own module scope, only lazily inside `init()`/`generate_metrics_output()`.

**Corrected during verification**: the `child_exit` hook's `multiprocess.mark_process_dead()` call only cleans up `gauge_{live-mode}_*.db` files (for `prometheus_client`'s native multiprocess "live" Gauge modes) — it does **not** clean up Counter/Histogram files, which correctly persist and keep contributing to aggregated totals forever, since a dead process's historical counts remain valid regardless of whether the process still exists. This module doesn't use live-mode Gauges at all (the on-demand collector pattern above sidesteps needing them), so the hook is currently a no-op — kept as forward-compatible hygiene, not because it's fixing an active leak. Confirmed via the same 2-worker smoke test: a killed worker's counter contributions remained correctly counted after it was gone.

**Files:** `src/qbt_rules/metrics.py` (new), `src/qbt_rules/cli.py`, `src/qbt_rules/server.py`, `src/qbt_rules/engine.py`, `src/qbt_rules/worker.py`, `src/qbt_rules/scheduler.py`, `pyproject.toml` (new `metrics` extra + pytest marker), `config/config.default.yml`. Tests: new `tests/unit/test_metrics.py`, `TestMetricsRoutes` in `test_server.py`; `tests/conftest.py` gained a session-wide `PROMETHEUS_MULTIPROC_DIR` setup (must be set before prometheus_client's first import anywhere in the pytest session, which a per-test fixture can't achieve) and a shared `reset_metrics_module_state` autouse fixture. Wiki: new `Metrics.md`, cross-linked from `Home.md`/`_Sidebar.md`/`HTTP-API-Reference.md`/`Architecture-Internals.md`/`Security.md`/`Scheduling.md`.

### 7. Remove `keep_files`, fix qBittorrent config, drop legacy shims

**Status**: Implemented.

A full audit for "legacy" code across the repo (prompted by wanting to remove all of it before release) surfaced a real, severe bug beyond routine cleanup: the **documented** `qbittorrent.username`/`.password` config.yml keys, and **every** `QBT_RULES_QBITTORRENT_*` environment variable (including `.host`), were silently non-functional — only the undocumented `user`/`pass` YAML keys ever worked, and only set directly in `config.yml`, never via env var. Every deployment path the repo documents (`README.md`, all `docker-compose*.yml` files, `config/config.default.yml`) showed the broken path. Root cause: `Config.get_qbittorrent_config()` read straight off `self.config` instead of going through `resolve_config()`/`resolve_section_config()` like every other section — the one section that never got migrated during the earlier config-architecture cleanup.

**Fix:** new `get_qbittorrent_config(args, config_obj)` in `cli.py`, using the same `resolve_section_config()` helper every other section already uses — `host`/`username`/`password` now genuinely support CLI args → `_FILE` env var → direct env var → config.yml → default, matching what was documented all along. `Config.get_qbittorrent_config()` removed entirely; the undocumented `user`/`pass` YAML key aliases dropped outright (`username`/`password` are the only accepted keys now) — this also let `ENV_VAR_MAP` shrink further, since the three canonical qbittorrent keys already matched the mechanical convention and needed no explicit entries at all. **Verified empirically** (not just unit-tested): started a real server with `QBT_RULES_QBITTORRENT_HOST`/`_USERNAME`/`_PASSWORD` set to values different from `config.yml`, confirmed the env var values won; confirmed a `config.yml` using only the old `user`/`pass` keys now resolves to defaults instead of silently succeeding.

**Also removed in this pass:**
- `keep_files` (see Initiative 1 above) — full removal, not just the deprecation window; `_resolve_delete_files()` collapsed to a single-line `return bool(params.get('delete_files', True))`.
- `--torrent-hash`, a hidden (`argparse.SUPPRESS`) undocumented alias for `--hash`, no stated removal target — confirmed gone from `--help` and now genuinely errors as an unrecognized argument.
- Stale/misleading documentation with no functional impact: a `create_parser()` docstring referencing a `trigger_type` parameter that hasn't existed since the v0.4.1 `--trigger` removal; a `test_api.py` module docstring claiming skipped legacy tests exist that don't; `config.default.yml`'s `engine.dry_run` section header claiming "legacy"/"backward compatibility" framing for a setting that was never actually deprecated, just an alternate (still fully supported) way to configure dry-run vs. the `--dry-run` CLI flag.

**Explicitly scoped out:** `CHANGELOG.md`'s v0.4.0 entry documents two deprecations (PyPI distribution, standalone CLI mode) with no later "Removed" entry; current code shows neither is gated/present anymore. This is a historical `CHANGELOG.md` documentation gap, not live code — left alone.

**Files:** `src/qbt_rules/engine.py`, `src/qbt_rules/cli.py`, `src/qbt_rules/config.py`, `src/qbt_rules/arguments.py`, `config/config.default.yml`. Tests: `tests/unit/test_engine/test_action_executor.py`, `tests/integration/test_rule_execution.py`, `tests/unit/test_config.py`, `tests/unit/test_cli.py` (new `TestGetQbittorrentConfig`, asserting real resolved values — the old tests only checked key presence, which is exactly how this bug went unnoticed), `tests/unit/test_arguments.py`, `tests/unit/test_api.py`. Wiki: `Actions.md`, `Frequently-Asked-Questions.md` (drop `keep_files` deprecation framing), `In‐Depth-Configuration.md` (fix the `qbittorrent.user`/`.pass` "still works" claim).

### 8. Resolve `_LOG` vs `_LOGGING` env var naming

**Status**: Implemented.

Same bug shape as Initiative 7's qBittorrent fix: `config.default.yml` documented `QBT_RULES_LOG_LEVEL`/`_FILE`/`_TRACE_MODE`/`_HTTP_ACCESS` (with claimed `_FILE`-suffix secret support) and `ENV_VAR_MAP` listed them as an exception to the mechanical `QBT_RULES_<SECTION>_<FIELD>` convention, but the actual code path — `Config.get_log_level()`/`get_log_file()`/`get_trace_mode()`, plus `logging.http_access` read via a third, separate `config_obj.get()` call — never touched `resolve_config()`/`ENV_VAR_MAP` at all. It read bare, unprefixed `LOG_LEVEL`/`LOG_FILE`/`TRACE_MODE` env vars directly, with zero `_FILE` support, and `http_access` had no env var support whatsoever.

**Fix:** new `get_logging_config(args, config_obj)` in `cli.py`, resolving all four fields (`level`, `file`, `trace_mode`, `http_access`) through `resolve_config()` individually rather than via `resolve_section_config()` — the established CLI flags are `--log-level`/`--trace` (`args.log_level`/`args.trace`), not the mechanically-derived `--logging-level`/`--logging-trace-mode` that helper would assume. Real env vars are now `QBT_RULES_LOGGING_*`, matching the convention exactly — no `ENV_VAR_MAP` exception needed, so the three `logging.*` entries were removed from the map entirely (only `engine.dry_run` remains as a genuine exception, having no section prefix at all). `Config.get_log_level()`/`get_log_file()`/`get_trace_mode()` removed entirely; `setup_logging()` now takes the pre-resolved dict instead of a `Config` object; `process_args()` no longer sets bare `LOG_LEVEL`/`TRACE_MODE` env vars as an indirection step. **Verified empirically**: started a real server with all four `QBT_RULES_LOGGING_*` env vars set to non-default values (level, file path, trace mode, http access), confirmed each took effect (including the detailed trace-mode log format and the overridden file path); confirmed the old bare `LOG_LEVEL`/`TRACE_MODE` env vars now have zero effect; confirmed `--log-level`/`--trace` CLI flags still work standalone with no env vars set.

**Identified but explicitly out of scope:** `Config.is_dry_run()` has the identical bug — reads bare `os.environ.get('DRY_RUN', ...)` instead of `QBT_RULES_DRY_RUN`, so the documented env var is silently dead the same way `QBT_RULES_LOG_*`/`QBT_RULES_QBITTORRENT_*` were. Flagged as a follow-up candidate, not fixed here — this task's scope was specifically the `_LOG`/`_LOGGING` naming inconsistency.

**Files:** `src/qbt_rules/cli.py` (new `get_logging_config()`), `src/qbt_rules/logging.py` (`setup_logging()` takes a dict), `src/qbt_rules/config.py` (removed 3 `Config` methods, trimmed `ENV_VAR_MAP`), `src/qbt_rules/arguments.py` (`process_args()` simplified), `config/config.default.yml` (`QBT_RULES_LOG_*` → `QBT_RULES_LOGGING_*`, 5 occurrences). Tests: `tests/unit/test_logging.py` (all of `TestSetupLogging` rewritten for the new dict-based signature), `tests/unit/test_config.py` (11 tests removed for deleted `Config` methods), `tests/unit/test_cli.py` (new `TestGetLoggingConfig`, 8 tests; `TestMain`/`TestRunServerMode` mock fixes), `tests/unit/test_arguments.py` (2 tests rewritten to confirm the old bare env vars are no longer set). Wiki: `In‐Depth-Configuration.md`, `Frequently-Asked-Questions.md`.

### 9. Audit `get_*_config()` architecture; fix `is_dry_run()`, dedupe config resolution

**Status**: Implemented.

Prompted by a direct question: is the per-section `get_*_config()` function shape in `cli.py` (9 functions) the right approach, or should it be consolidated? Conclusion: the shape is correct and stays — it mirrors `config.yml`'s own structure and is the exact pattern that made the qbittorrent/logging bugs (Initiatives 7-8) fixable. Collapsing it into `Config` methods was explicitly rejected: that's the anti-pattern that *caused* those bugs (a `Config` method silently reading `os.environ` directly instead of going through `resolve_config()`).

The audit did surface one more instance of that same bug family, plus two small cleanups, scoped down to a minimal fix (explicitly declined: threading `client_config` through 6 function signatures — real diff, zero behavior change, since `main()` dispatches to exactly one client-mode command per process; `get_integrations_config`'s hand-rolled nesting; `get_schedule_config`'s parallel env-override mechanism — all left alone as structural, not bugs):

- **`Config.is_dry_run()` fixed** (same bug as qbittorrent/logging): read bare `os.environ.get('DRY_RUN', ...)` directly, even though `ENV_VAR_MAP` already declared `'engine.dry_run': 'QBT_RULES_DRY_RUN'` — a mapping nothing consulted. Now routes through `resolve_config()` + `parse_bool()`, gaining `_FILE` secret support for free. Companion fix: `process_args()`'s `--dry-run` → env-var indirection (needed since `is_dry_run()` is called from `worker.py` deep inside job execution, with no `args` in scope) now sets `QBT_RULES_DRY_RUN` instead of the dead `DRY_RUN`. **Verified empirically**: direct `Config.is_dry_run()` checks with each of `DRY_RUN=true` (now False/inert), `QBT_RULES_DRY_RUN=true` (True), and no env vars (False); also confirmed live against a real server for both `QBT_RULES_DRY_RUN=true` and standalone `--dry-run`.
- **`run_server_mode()` no longer re-resolves `logging_config`**: it was calling `get_logging_config()` a second time just to read `['http_access']`, despite `main()` already resolving the identical dict one call earlier for `setup_logging()`. Now threaded through as a parameter.
- **`Config.get()` deduped**: it re-implemented the same dot-notation traversal as the standalone `get_nested_config()` (already used by `resolve_config()`). `get_nested_config()` gained an optional `default` param; `Config.get()` now just delegates to it. Pure behavior-preserving dedup.
- **Incidental fix while implementing**: `tests/conftest.py`'s global `clean_environment_variables` safety-net fixture still only scrubbed the old `DRY_RUN`/`LOG_LEVEL`/`TRACE_MODE` names. It had been silently masking a `monkeypatch.delenv()` quirk in `test_arguments.py`'s local fixture (deleting an env var that was never *set* via monkeypatch doesn't get tracked for auto-restore, so a local cleanup can get undone by monkeypatch's own finalizer) — this only became visible once the dry-run env var was renamed and the global fixture no longer matched. Fixed to track `QBT_RULES_DRY_RUN`; the dead `LOG_LEVEL`/`TRACE_MODE` entries (already fully dead from Initiative 8) were dropped.

**Files:** `src/qbt_rules/config.py` (`is_dry_run()`, `get_nested_config()`, `Config.get()`), `src/qbt_rules/arguments.py` (`process_args()`), `src/qbt_rules/cli.py` (`run_server_mode()` signature). Tests: `tests/unit/test_config.py`, `tests/unit/test_arguments.py`, `tests/unit/test_cli.py`, `tests/conftest.py`.

### Sequencing

Initiatives 3 and 4 share the same `ActionExecutor`/`RulesEngine` signature change (adding `config`) — land once, rebase the other. Initiative 5's `create_app()` signature change (adding `config`, for the rules view) is independent. Initiative 6's fork-safety design directly reuses Initiative 2's established pre-fork/no-post_fork-restart pattern, but has no code-level shared surface with any other initiative. Initiative 7 touches `keep_files` (shared with Initiative 1, landed after it) and qBittorrent config resolution (a new, previously-unmigrated section — no shared surface with Initiatives 2-6). Initiative 8 follows the exact same pattern as Initiative 7's qBittorrent fix but for `logging.*` — no shared surface with any other initiative beyond the precedent. Initiative 9 follows the same pattern again for `engine.dry_run`, and additionally touches `run_server_mode()`'s signature (Initiative 8 also touches that function, landed before it) and `Config.get()` (no shared surface elsewhere). Initiatives 1 and 2 have no shared surface with anything else.

Once everything above is merged to `main`: `scripts/bump-version.sh minor` (0.5.x → 0.6.0).

---

## v0.7.0 Planning

**Status**: Nothing currently planned. Both items originally scoped here — Prometheus metrics and the `keep_files` removal — were rolled into v0.6.0 instead (Initiatives 6 and 7 above), since nothing had been tagged/released yet and there was no reason to split either across two release cycles.

---

## Risk Mitigation

### Risk: Queue Database Corruption

**Mitigation**:
- SQLite: WAL mode for crash safety
- Automatic schema migration with backups
- Health check monitors queue integrity

### Risk: Worker Thread Crash

**Mitigation**:
- Worker monitors own health, restarts if needed
- Health check detects unresponsive worker
- Supervisor process (Docker restart policy)

### Risk: API Key Compromise

**Mitigation**:
- Use strong random keys (generate with `openssl rand -hex 32`)
- Support key rotation without downtime
- Rate limiting (future enhancement)
- Access logs for auditing

### Risk: Breaking Changes Impact

**Mitigation**:
- Version clearly marked as breaking (0.4.0)
- Migration guide in documentation
- Only single user (no widespread impact)
- Docker-only distribution simplifies deployment

---

## Open Questions

1. **Rate Limiting**: Do we need rate limiting for API endpoints?
   - *Decision*: Defer to future version, not critical for home use

2. **Authentication Methods**: Support tokens beyond API keys?
   - *Decision*: API keys sufficient for v0.4.0, tokens in future

3. **Job Priority**: Should jobs have priority levels?
   - *Decision*: Defer to future, FIFO sufficient initially

4. **Webhook Retry**: Should failed webhooks be retried?
   - *Decision*: No automatic retry, requester's responsibility

5. **Cross-Seeding**: Include in v0.4.0 or defer?
   - *Decision*: Architecture planning only, implementation deferred

---

## Timeline Estimate

**Total Estimated Time**: 40-60 hours

| Phase | Estimated Hours | Dependencies |
|-------|----------------|--------------|
| 0. Planning | 4h | None |
| 1. Config System | 4h | None |
| 2. Queue System | 8h | Phase 1 |
| 3. Worker | 4h | Phase 2 |
| 4. API Server | 6h | Phase 2, 3 |
| 5. CLI Refactor | 4h | Phase 4 |
| 6. qbittorrent-api | 3h | None (parallel) |
| 7. Redis Backend | 4h | Phase 2 |
| 8. Terminology | 2h | Anytime |
| 9. Docker | 4h | All core |
| 10. Documentation | 6h | All complete |
| 11. Testing | 8h | All complete |
| 12. Release Prep | 3h | All complete |

**Note**: Phases 1, 6, 8 can run in parallel

---

## Glossary

**Context**: Execution filter for rules (replaces "trigger"). Examples: scheduled, on_added, on_completed

**Job**: Unit of work in queue. Contains context, hash filter, status, and result

**Queue Backend**: Persistence layer for jobs (SQLite or Redis)

**Worker**: Background process that executes queued jobs

**API Key**: Authentication token for HTTP API access

**_FILE Pattern**: Environment variable variant that reads value from file path

---

## References

- [qBittorrent Web API Documentation](https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-(qBittorrent-4.1))
- [qbittorrent-api Package](https://github.com/rmartin16/qbittorrent-api)
- [Flask Documentation](https://flask.palletsprojects.com/)
- [Gunicorn Documentation](https://docs.gunicorn.org/)
- [Docker Best Practices](https://docs.docker.com/develop/dev-best-practices/)
- [cross-seed Documentation](https://www.cross-seed.org/docs/)

---

**Document Version**: 1.0
**Last Updated**: 2025-12-13
**Author**: qbt-rules development team
**Status**: ✅ Approved - Ready for Implementation
