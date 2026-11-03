"""
Reading and writing the config files the web editor works on

EditableFile wraps one file (rules.yml) with what a browser editor needs:

- An ETag (sha256 of the bytes on disk) handed out with every read, and
  required back with every write -- a write whose ETag no longer matches
  the file is refused with the file's current content, whoever changed it
  (another browser tab, a host-side editor, `docker cp`).
- Writes that never leave a half-written file: a temp file in the same
  directory, fsynced, then os.replace()d over the original. When the file
  is itself a single-file Docker bind mount, replace() fails with EBUSY
  (the mount point can't be swapped out from under the mount), so that one
  case falls back to rewriting the file in place -- not atomic, which is
  why the backup below is taken first.
- A backup of the previous content in the history directory (.history/
  in the state directory, /var/lib/qbt-rules) on every save that changes
  anything, keeping the newest HISTORY_KEEP.
- A missing file reads as empty, and the first save creates it -- so the
  editor works on a fresh install with no rules.yml yet.
- A file the user made read-only (chmod 444) stays read-only: writable()
  reports it and write() refuses, rather than replace() quietly swapping
  in a new writable file (which a writable directory would allow).

An fcntl lock (in the history directory) serialises the check-then-write across Gunicorn worker
processes, each of which has its own EditableFile.

redacted_config_view() is the read-only counterpart for config.yaml, which
holds credentials and is only read at startup -- see its docstring.
"""

import contextlib
import errno
import hashlib
import logging
import os
import re
import stat
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

try:
    import fcntl
except ImportError:  # pragma: no cover - not POSIX
    fcntl = None  # type: ignore[assignment]  # checked before use; POSIX-only module

from qbt_rules.config import ALIASES, ENV_PREFIX

logger = logging.getLogger(__name__)

HISTORY_KEEP = 20

# rules.yml.20261021T031542123456Z -- UTC, microseconds so two saves in
# one second don't collide
_VERSION_ID = re.compile(r"^\d{8}T\d{12}Z$")


class FileConflictError(Exception):
    """The file changed since the caller read it"""

    def __init__(self, current: "FileSnapshot"):
        super().__init__("File changed on disk")
        self.current = current


class FileNotWritableError(Exception):
    """Saving is turned off, or the file/directory can't be written"""


@dataclass
class FileSnapshot:
    text: str
    etag: str
    modified_at: str | None
    size: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.text,
            "etag": self.etag,
            "modified_at": self.modified_at,
            "size": self.size,
        }


def compute_etag(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat()


def _nearest_existing(path: Path) -> Path:
    """path, or its closest ancestor that exists (what mkdir -p would need to write)"""
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


class EditableFile:
    def __init__(self, path: Path, history_dir: Path, keep: int = HISTORY_KEEP):
        self.path = Path(path)
        self.history_dir = Path(history_dir)
        self.keep = keep

    # -- reading ------------------------------------------------------------

    def read(self) -> FileSnapshot:
        """The file's content; a missing file is empty, with no modified_at"""
        try:
            data = self.path.read_bytes()
        except FileNotFoundError:
            return FileSnapshot(text="", etag=compute_etag(b""), modified_at=None, size=0)
        st = self.path.stat()
        return FileSnapshot(
            text=data.decode("utf-8"),
            etag=compute_etag(data),
            modified_at=_iso(st.st_mtime),
            size=len(data),
        )

    def writable(self) -> tuple[bool, str | None]:
        """(can save, why not) -- checked before every write, and shown in
        the editor up front so it opens read-only instead of failing on save"""
        if not self.path.exists():
            if not os.access(self.path.parent, os.W_OK | os.X_OK):
                return (
                    False,
                    f"{self.path.name} does not exist and {self.path.parent} is not writable, so "
                    "it can't be created here",
                )
        elif not os.access(self.path, os.W_OK):
            try:
                mode = stat.S_IMODE(self.path.stat().st_mode)
                return (
                    False,
                    f"{self.path.name} is read-only on disk (mode {mode:04o}) -- make it writable "
                    "to edit here",
                )
            except OSError as e:
                return False, f"{self.path.name} cannot be read: {e.strerror}"
        history = _nearest_existing(self.history_dir)
        if not os.access(history, os.W_OK | os.X_OK):
            return False, f"{history} is not writable, so backups can't be kept"
        return True, None

    # -- writing ------------------------------------------------------------

    @contextmanager
    def _lock(self) -> Iterator[None]:
        self.history_dir.mkdir(parents=True, exist_ok=True)
        if fcntl is None:  # pragma: no cover
            yield
            return
        with open(self.history_dir / f".{self.path.name}.lock", "a") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)

    def write(self, text: str, if_match: str) -> tuple[FileSnapshot, bool]:
        """
        Replace the file's content, if it's still what the caller last read

        Args:
            text: The new content
            if_match: The ETag from the caller's last read

        Returns:
            (snapshot after the write, whether anything changed)

        Raises:
            FileNotWritableError: The file or its directory can't be written
            FileConflictError: The file no longer matches if_match
        """
        ok, reason = self.writable()
        if not ok:
            raise FileNotWritableError(reason)

        new_data = text.encode("utf-8")
        with self._lock():
            existed = self.path.exists()
            current = self.read()
            if if_match != current.etag:
                raise FileConflictError(current)
            if existed and new_data == current.text.encode("utf-8"):
                return current, False

            if existed:
                self._backup(current.text.encode("utf-8"))
                self._replace(new_data)
                kept = f"previous version kept in {self.history_dir}"
            else:
                self._create(new_data)
                kept = "created"
            logger.info(
                f"{self.path.name} saved from the web editor ({len(new_data)} bytes, {kept})"
            )
            return self.read(), True

    def _create(self, data: bytes) -> None:
        """Write a new file: exclusive, so a file that appeared meanwhile isn't overwritten"""
        try:
            with open(self.path, "xb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        except FileExistsError:
            raise FileConflictError(self.read()) from None

    def _replace(self, data: bytes) -> None:
        st = self.path.stat()
        tmp: str | None = None
        try:
            fd, tmp = tempfile.mkstemp(
                prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
            )
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            # mkstemp creates 0600 files owned by whoever we run as -- keep
            # the original's mode, and its owner where we're allowed to
            os.chmod(tmp, stat.S_IMODE(st.st_mode))
            with contextlib.suppress(PermissionError, AttributeError):
                os.chown(tmp, st.st_uid, st.st_gid)
            os.replace(tmp, self.path)
        except OSError as e:
            if tmp is not None:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
            if e.errno not in (errno.EBUSY, errno.EXDEV, errno.EACCES, errno.EPERM):
                raise
            # A single-file bind mount (EBUSY, EXDEV), or a writable file in a
            # directory we can't write (EACCES, EPERM): rewrite in place instead
            logger.debug(f"Atomic replace of {self.path} failed ({e.strerror}); rewriting in place")
            with open(self.path, "r+b") as f:
                f.write(data)
                f.truncate()
                f.flush()
                os.fsync(f.fileno())
            return

        try:
            dir_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass

    # -- history ------------------------------------------------------------

    def _backup(self, data: bytes) -> None:
        version_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        (self.history_dir / f"{self.path.name}.{version_id}").write_bytes(data)
        for old in self._versions()[self.keep :]:
            with contextlib.suppress(OSError):
                old[1].unlink()

    def _versions(self) -> list[tuple[str, Path]]:
        """(id, path) newest first"""
        prefix = f"{self.path.name}."
        found = []
        if self.history_dir.is_dir():
            for p in self.history_dir.iterdir():
                if p.name.startswith(prefix) and _VERSION_ID.match(p.name[len(prefix) :]):
                    found.append((p.name[len(prefix) :], p))
        return sorted(found, reverse=True)

    def history(self) -> list[dict[str, Any]]:
        out = []
        for version_id, p in self._versions():
            saved = datetime.strptime(version_id, "%Y%m%dT%H%M%S%fZ").replace(tzinfo=UTC)
            out.append({"id": version_id, "saved_at": saved.isoformat(), "size": p.stat().st_size})
        return out

    def read_version(self, version_id: str) -> str | None:
        if not _VERSION_ID.match(version_id or ""):
            return None
        p = self.history_dir / f"{self.path.name}.{version_id}"
        return p.read_text("utf-8") if p.is_file() else None


# ---------------------------------------------------------------------------
# The config file (config.yaml), read-only
# ---------------------------------------------------------------------------

_SECRET_KEY = re.compile(
    r"(api_key|apikey|password|passwd|secret|token|webhook_url|redis_url)$", re.IGNORECASE
)
REDACTED = "<redacted>"


def _env_vars_for(config_key: str) -> list[str]:
    """The variables that override a config-file key: its own name (interpose's
    QBT_RULES_<KEY>), and for an aliased key (server.port, listen.port) the other's"""
    keys = [config_key]
    keys += [new for old, new in ALIASES.items() if old == config_key]
    keys += [old for old, new in ALIASES.items() if new == config_key]
    return [ENV_PREFIX + key.upper().replace(".", "_") for key in keys]


def redacted_config_view(text: str, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """
    The config file (config.yaml) for display: credentials masked, env overrides pointed out

    Read-only on purpose. config.yaml is read once at startup (nothing in it
    applies until a restart), its secrets can't round-trip through a masked
    view without merging them back in, and a bad save there stops the
    server from starting rather than leaving old rules running.

    Any scalar under a key that looks like a credential is replaced with
    "<redacted>" -- unless it's a ${VAR} reference, which names a variable
    rather than holding a secret. Each key an environment variable
    overrides gets an info issue, since editing the file wouldn't change
    what the server uses.

    Returns:
        {'content': str, 'redacted': [paths], 'issues': [issue dicts]}
    """
    environ = os.environ if environ is None else environ
    try:
        root = yaml.compose(text)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        return {
            "content": "",
            "redacted": [],
            "issues": [
                {
                    "severity": "error",
                    "message": f"The config file has a YAML syntax error, so it is not shown: {e}",
                    "path": "",
                    "line": mark.line + 1 if mark else None,
                    "column": mark.column + 1 if mark else None,
                    "end_line": None,
                    "end_column": None,
                }
            ],
        }

    spans: list[tuple[int, int]] = []
    redacted: list[str] = []
    issues: list[dict[str, Any]] = []

    def walk(node: yaml.Node, path: list[str]) -> None:
        if isinstance(node, yaml.MappingNode):
            for key_node, value_node in node.value:
                if not isinstance(key_node, yaml.ScalarNode):
                    continue
                key_path = [*path, str(key_node.value)]
                dotted = ".".join(key_path)
                if isinstance(value_node, yaml.ScalarNode):
                    if (
                        _SECRET_KEY.search(key_node.value)
                        and value_node.value
                        and not str(value_node.value).startswith("${")
                    ):
                        spans.append((value_node.start_mark.index, value_node.end_mark.index))
                        redacted.append(dotted)
                    names = [n for v in _env_vars_for(dotted) for n in (f"{v}_FILE", v)]
                    for name in names:
                        if name in environ:
                            issues.append(
                                {
                                    "severity": "info",
                                    "message": f"Overridden by the {name} environment variable -- "
                                    f"the value here is not used",
                                    "path": dotted,
                                    "line": key_node.start_mark.line + 1,
                                    "column": key_node.start_mark.column + 1,
                                    "end_line": key_node.end_mark.line + 1,
                                    "end_column": key_node.end_mark.column + 1,
                                }
                            )
                            break
                elif dotted == "schedule" and "QBT_RULES_SCHEDULE_0_CRON" in environ:
                    issues.append(
                        {
                            "severity": "info",
                            "message": (
                                "Replaced by the QBT_RULES_SCHEDULE_<N>_CRON environment variables"
                            ),
                            "path": dotted,
                            "line": key_node.start_mark.line + 1,
                            "column": key_node.start_mark.column + 1,
                            "end_line": None,
                            "end_column": None,
                        }
                    )
                walk(value_node, key_path)

    if root is not None:
        walk(root, [])

    out = text
    for start, end in sorted(spans, reverse=True):
        out = out[:start] + f'"{REDACTED}"' + out[end:]

    return {"content": out, "redacted": redacted, "issues": issues}
