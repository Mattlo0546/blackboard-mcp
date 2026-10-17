"""Offline tests: `uv run --with pytest pytest`. No Blackboard account or network needed."""
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
(TMP / "slidemate").mkdir()
(TMP / "slidemate" / "config.json").write_text(json.dumps({"library_roots": [str(TMP / "Slides")]}))
os.environ.update(BB_MCP_HOME=str(TMP / "home"), SLIDEMATE_DATA=str(TMP / "slidemate"), BB_BASE_URL="learn.example.ac.uk/ultra")
os.environ.pop("BB_DOWNLOAD_DIR", None)

from blackboard_mcp.bb import Course  # noqa: E402
from blackboard_mcp.config import load_settings  # noqa: E402
from blackboard_mcp.sync import Syncer, current_courses, parse_week  # noqa: E402

NOW = datetime(2026, 10, 17, tzinfo=timezone.utc)


def course(code, created, end=None):
    avail = {"available": "Yes", "duration": {"type": "DateRange", "end": end} if end else {"type": "Continuous"}}
    return Course(id=code, course_id=code, name=code, code=code, raw={"created": created, "availability": avail})


def test_settings():
    s = load_settings()
    assert s.base_url == "https://learn.example.ac.uk"
    assert s.download_dir == TMP / "Slides"  # SlideMate's library


def test_only_this_years_courses():
    cs = [course("NEW1", "2026-06-15T00:00:00Z"), course("NEW2", "2026-06-15T00:00:00Z"),
          course("OLD1", "2025-04-04T00:00:00Z"), course("ENDED", "2026-06-15T00:00:00Z", end="2026-01-01T00:00:00Z"),
          course("ENDS_LATER", "2024-01-01T00:00:00Z", end="2027-06-01T00:00:00Z")]
    assert [c.id for c in current_courses(cs, NOW)] == ["NEW1", "NEW2", "ENDS_LATER"]


def test_week_folders():
    assert parse_week("Week 3 - Sensing Mechanisms") == 3
    assert parse_week("Lecture 12 slides") == 12
    assert parse_week("Unit information") is None


class FakeBB:
    def __init__(self):
        self.downloads = []

    def walk(self, pk):
        yield (), {"id": "1", "title": "Week 1", "contentHandler": {"id": "resource/x-bb-folder"}}
        yield ("Week 1",), {"id": "2", "title": "Lecture 1 slides", "modified": "m1",
                            "contentHandler": {"id": "resource/x-bb-file"}}
        yield (), {"id": "3", "title": "Welcome to the unit", "modified": "m1"}

    def attachments(self, pk, cid):
        return [{"id": "a", "fileName": "Lecture 1.pdf"}, {"id": "b", "fileName": "recording.mp4"}] if cid == "2" else \
               [{"id": "c", "fileName": "welcome.pdf"}]

    def attachment_url(self, pk, cid, aid):
        return f"/x/{cid}/{aid}"

    def download(self, url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"%PDF")
        self.downloads.append(url)


def test_sync_layout_skips_noise_and_repeats():
    s = load_settings()
    bb = FakeBB()
    rep = Syncer(s, bb).sync_course(course("ABC123", "2026-06-15T00:00:00Z"))
    assert rep["downloaded"] == 1 and bb.downloads == ["/x/2/a"]  # PDFs only; the welcome page is skipped
    assert (s.download_dir / "ABC123" / "Week 01" / "Lecture 1.pdf").exists()
    syncer = Syncer(s, bb)
    syncer.state["files"]["ABC123:2:a"] = "m1"
    assert syncer.sync_course(course("ABC123", "2026-06-15T00:00:00Z"))["downloaded"] == 0


def test_stdio_lists_tools_and_keeps_stdout_clean():
    p = subprocess.Popen([sys.executable, "-m", "blackboard_mcp.cli", "serve"], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        def rpc(mid, method, params=None):
            p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}}) + "\n")
            p.stdin.flush()
            return json.loads(p.stdout.readline())
        rpc(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        names = {t["name"] for t in rpc(2, "tools/list")["result"]["tools"]}
        assert {"bb_login", "bb_sync", "bb_sync_status", "bb_upcoming", "bb_announcements"} <= names
    finally:
        p.kill()
