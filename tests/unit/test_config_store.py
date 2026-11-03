"""
Tests for config_store.py - how the rules editor reads and writes files
"""

import errno
import os
import stat
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from qbt_rules.config_store import (
    EditableFile,
    FileConflictError,
    FileNotWritableError,
    compute_etag,
    redacted_config_view,
)


@pytest.fixture
def rules_file(tmp_path):
    # rules.yml beside the config file (/etc/qbt-rules in the image)
    (tmp_path / "etc").mkdir()
    path = tmp_path / "etc" / "rules.yml"
    path.write_text("rules: []  # original\n")
    path.chmod(0o640)
    return path


@pytest.fixture
def history_dir(tmp_path: Path) -> Path:
    # Its history in the state directory (/var/lib/qbt-rules/.history in the image)
    return tmp_path / "state" / ".history"


@pytest.fixture
def store(rules_file, history_dir):
    return EditableFile(rules_file, history_dir)


class TestRead:
    def test_read_returns_content_and_etag(self, store, rules_file):
        snap = store.read()
        assert snap.text == "rules: []  # original\n"
        assert snap.etag == compute_etag(rules_file.read_bytes())
        assert snap.size == len(snap.text)
        assert snap.modified_at


class TestWrite:
    def test_write_replaces_content_and_keeps_a_backup(self, store, rules_file):
        etag = store.read().etag
        snap, changed = store.write("rules: []  # edited\n", etag)

        assert changed
        assert rules_file.read_text() == "rules: []  # edited\n"
        assert snap.etag == compute_etag(b"rules: []  # edited\n")
        [version] = store.history()
        assert store.read_version(version["id"]) == "rules: []  # original\n"

    def test_write_keeps_file_mode(self, store, rules_file):
        store.write("rules: []\n", store.read().etag)
        assert stat.S_IMODE(rules_file.stat().st_mode) == 0o640

    def test_write_leaves_no_temp_files(self, store, rules_file):
        store.write("rules: []\n", store.read().etag)
        assert sorted(p.name for p in rules_file.parent.iterdir()) == ["rules.yml"]

    def test_stale_etag_is_a_conflict_carrying_the_current_file(self, store, rules_file):
        etag = store.read().etag
        rules_file.write_text("rules: []  # changed elsewhere\n")

        with pytest.raises(FileConflictError) as exc:
            store.write("rules: []  # mine\n", etag)

        assert exc.value.current.text == "rules: []  # changed elsewhere\n"
        assert rules_file.read_text() == "rules: []  # changed elsewhere\n"
        assert store.history() == []

    def test_unchanged_content_is_not_written_or_backed_up(self, store, rules_file):
        snap = store.read()
        _, changed = store.write(snap.text, snap.etag)
        assert not changed
        assert store.history() == []

    def test_read_only_file_is_respected(self, store, rules_file):
        """chmod 444 means "don't edit" -- the writable directory would let
        a replace() through, so this has to be checked explicitly"""
        if os.geteuid() == 0:
            pytest.skip("root ignores file permissions")
        rules_file.chmod(0o444)

        ok, reason = store.writable()
        assert not ok
        assert "0444" in reason
        with pytest.raises(FileNotWritableError):
            store.write("rules: []\n", store.read().etag)
        assert rules_file.read_text() == "rules: []  # original\n"

    def test_single_file_bind_mount_falls_back_to_in_place_write(self, store, rules_file, mocker):
        """os.replace() onto a bind-mounted file fails with EBUSY"""
        mocker.patch(
            "qbt_rules.config_store.os.replace",
            side_effect=OSError(errno.EBUSY, "Device or resource busy"),
        )
        inode = rules_file.stat().st_ino

        _, changed = store.write("rules: []  # in place\n", store.read().etag)

        assert changed
        assert rules_file.read_text() == "rules: []  # in place\n"
        assert rules_file.stat().st_ino == inode
        assert not [p for p in rules_file.parent.iterdir() if p.name.endswith(".tmp")]

    def test_other_replace_errors_propagate(self, store, rules_file, mocker):
        mocker.patch(
            "qbt_rules.config_store.os.replace", side_effect=OSError(errno.EIO, "I/O error")
        )
        with pytest.raises(OSError):
            store.write("rules: []  # x\n", store.read().etag)
        assert rules_file.read_text() == "rules: []  # original\n"
        assert not [p for p in rules_file.parent.iterdir() if p.name.endswith(".tmp")]


class TestHistory:
    def test_history_is_newest_first_and_pruned(self, rules_file, history_dir):
        store = EditableFile(rules_file, history_dir, keep=3)
        for n in range(5):
            store.write(f"rules: []  # v{n}\n", store.read().etag)

        versions = store.history()
        assert len(versions) == 3
        contents = [store.read_version(v["id"]) for v in versions]
        assert contents == ["rules: []  # v3\n", "rules: []  # v2\n", "rules: []  # v1\n"]

    @pytest.mark.parametrize(
        "bad_id", ["../rules.yml", "", "x", "20261021T000000000000Z/../../etc"]
    )
    def test_read_version_rejects_bad_ids(self, store, bad_id):
        assert store.read_version(bad_id) is None

    def test_read_version_missing(self, store):
        assert store.read_version("20200101T000000000000Z") is None


class TestRedactedConfigView:
    CONFIG = (
        "server:\n"
        "  api_key: hunter2\n"
        "  port: 5000\n"
        "qbittorrent:\n"
        '  password: "s3cret"  # keep comment\n'
        "  username: admin\n"
        "notifications:\n"
        "  webhook_url: ${WEBHOOK}\n"
        "integrations:\n"
        "  sonarr:\n"
        "    api_key: abc123\n"
    )

    def test_secrets_are_masked(self):
        view = redacted_config_view(self.CONFIG, environ={})
        content = view["content"]
        for secret in ("hunter2", "s3cret", "abc123"):
            assert secret not in content
        assert "# keep comment" in content
        assert "username: admin" in content
        assert set(view["redacted"]) == {
            "server.api_key",
            "qbittorrent.password",
            "integrations.sonarr.api_key",
        }

    def test_env_references_are_not_masked(self):
        view = redacted_config_view(self.CONFIG, environ={})
        assert "${WEBHOOK}" in view["content"]

    def test_masked_output_is_still_valid_yaml(self):
        import yaml

        data = yaml.safe_load(redacted_config_view(self.CONFIG, environ={})["content"])
        assert data["server"]["api_key"] == "<redacted>"
        assert data["server"]["port"] == 5000

    def test_env_overrides_are_reported(self):
        view = redacted_config_view(
            self.CONFIG,
            environ={
                "QBT_RULES_SERVER_PORT": "6000",
                "QBT_RULES_QBITTORRENT_PASSWORD_FILE": "/run/secrets/x",
            },
        )
        by_path = {i["path"]: i for i in view["issues"]}
        assert "QBT_RULES_SERVER_PORT" in by_path["server.port"]["message"]
        assert by_path["server.port"]["line"] == 3
        assert "QBT_RULES_QBITTORRENT_PASSWORD_FILE" in by_path["qbittorrent.password"]["message"]

    def test_syntax_error_shows_nothing(self):
        view = redacted_config_view("server: [\n  api_key: hunter2\n", environ={})
        assert view["content"] == ""
        assert view["issues"][0]["severity"] == "error"


class TestFirstSave:
    """No rules.yml yet (a fresh install): it reads as empty and the first save creates it"""

    def test_missing_file_reads_as_empty(self, tmp_path: Path, history_dir: Path) -> None:
        snap = EditableFile(tmp_path / "rules.yml", history_dir).read()
        assert (snap.text, snap.size, snap.modified_at) == ("", 0, None)
        assert snap.etag == compute_etag(b"")

    def test_first_save_creates_the_file(self, tmp_path: Path, history_dir: Path) -> None:
        path = tmp_path / "rules.yml"
        store = EditableFile(path, history_dir)
        assert store.writable() == (True, None)

        snap, changed = store.write("rules: []\n", store.read().etag)

        assert changed
        assert path.read_text() == "rules: []\n"
        assert snap.etag == compute_etag(b"rules: []\n")
        assert store.history() == []  # nothing to keep a copy of

    def test_a_file_that_appeared_meanwhile_is_a_conflict(
        self, tmp_path: Path, history_dir: Path
    ) -> None:
        path = tmp_path / "rules.yml"
        store = EditableFile(path, history_dir)
        etag = store.read().etag
        path.write_text("rules: []  # someone else's\n")
        with pytest.raises(FileConflictError):
            store.write("rules: []  # mine\n", etag)
        assert path.read_text() == "rules: []  # someone else's\n"

    def test_cannot_create_in_a_read_only_directory(
        self, tmp_path: Path, history_dir: Path
    ) -> None:
        if os.geteuid() == 0:
            pytest.skip("root ignores directory permissions")
        etc = tmp_path / "etc"
        etc.mkdir(mode=0o555)
        try:
            ok, reason = EditableFile(etc / "rules.yml", history_dir).writable()
        finally:
            etc.chmod(0o755)
        assert not ok
        assert reason is not None
        assert "does not exist" in reason


class TestPermissions:
    def test_history_directory_must_be_writable(self, rules_file: Path, tmp_path: Path) -> None:
        if os.geteuid() == 0:
            pytest.skip("root ignores directory permissions")
        state = tmp_path / "state"
        state.mkdir(mode=0o555)
        try:
            ok, reason = EditableFile(rules_file, state / ".history").writable()
        finally:
            state.chmod(0o755)
        assert not ok
        assert reason is not None
        assert "backups can't be kept" in reason

    def test_writable_file_in_a_read_only_directory_is_rewritten_in_place(
        self, rules_file: Path, history_dir: Path, mocker: MockerFixture
    ) -> None:
        """A single-file mount (Kubernetes subPath): the directory around it can't be written"""
        mocker.patch(
            "qbt_rules.config_store.tempfile.mkstemp",
            side_effect=PermissionError(errno.EACCES, "Permission denied"),
        )
        store = EditableFile(rules_file, history_dir)
        inode = rules_file.stat().st_ino

        _, changed = store.write("rules: []  # in place\n", store.read().etag)

        assert changed
        assert rules_file.read_text() == "rules: []  # in place\n"
        assert rules_file.stat().st_ino == inode
        assert len(store.history()) == 1


def test_alias_variables_are_reported() -> None:
    view = redacted_config_view("listen:\n  port: 5000\n", environ={"QBT_RULES_SERVER_PORT": "1"})
    assert "QBT_RULES_SERVER_PORT" in view["issues"][0]["message"]
