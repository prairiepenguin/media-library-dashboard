import json

from music_library.sync_health import SyncHealth, sanitize_error


def test_sync_health_preserves_last_success_when_a_new_run_starts(tmp_path):
    path = tmp_path / "sync_status.json"
    health = SyncHealth(path)
    health.start("music_scan")
    health.succeed("music_scan", {"tracks": 42})
    previous_success = json.loads(path.read_text())["stages"]["music_scan"]["last_success"]

    health.start("music_scan")
    stage = json.loads(path.read_text())["stages"]["music_scan"]

    assert stage["status"] == "running"
    assert stage["last_success"] == previous_success
    assert stage["details"] == {"tracks": 42}


def test_sync_health_records_sanitized_errors(tmp_path):
    path = tmp_path / "sync_status.json"
    health = SyncHealth(path)
    health.fail("plex_export", RuntimeError("failed /private/media/file token=supersecret"))

    stage = json.loads(path.read_text())["stages"]["plex_export"]

    assert stage["status"] == "error"
    assert "supersecret" not in stage["error"]
    assert "/private" not in stage["error"]
    assert stage["last_error_message"] == stage["error"]

    health.succeed("plex_export")
    recovered = json.loads(path.read_text())["stages"]["plex_export"]
    assert recovered["status"] == "success"
    assert recovered["error"] == ""
    assert recovered["last_error_message"] == stage["last_error_message"]


def test_sanitize_error_removes_urls():
    result = sanitize_error(RuntimeError("request failed https://example.test/?token=secret"))

    assert "example.test" not in result
    assert "secret" not in result
