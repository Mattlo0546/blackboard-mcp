"""MCP server exposing a Blackboard Learn (Ultra) site to AI tools."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

import anyio
from mcp.server.fastmcp import FastMCP

from .auth import LoginRequired, browser_login
from .bb import Blackboard, body_links, handler_id, html_to_text, parse_dt
from .config import load_settings
from .sync import Syncer, safe

mcp = FastMCP(
    "blackboard",
    instructions=(
        "Tools for the student's Blackboard (Ultra). bb_courses lists current courses; bb_browse shows a course's "
        "content; bb_upcoming lists due dates; bb_announcements shows recent announcements; bb_download saves one "
        "item's files; bb_sync downloads every current course's PDFs (check bb_sync_status). If any tool reports "
        "that sign-in is needed, call bb_login, which opens a browser window for the university sign-in."
    ),
)

_settings = load_settings()
_job: dict = {"running": False}
_job_lock = threading.Lock()


def _bb() -> Blackboard:
    if not _settings.base_url:
        raise LoginRequired("No Blackboard address set. Set BB_BASE_URL to your university's Blackboard, "
                            "e.g. https://learn.example.ac.uk.")
    return Blackboard(_settings)


async def _run(fn, *args):
    try:
        return await anyio.to_thread.run_sync(lambda: fn(*args))
    except LoginRequired as e:
        return {"login_required": True, "message": str(e)}
    except (ValueError, PermissionError) as e:
        return {"error": str(e)}


@mcp.tool()
async def bb_login(timeout_seconds: int = 300) -> dict:
    """Sign in to Blackboard. Opens a Chrome window at the university sign-in page; the student completes it
    there (SSO + MFA). Tries a silent refresh first, so it often finishes without any window."""
    def go():
        res = browser_login(_settings, headless=True)
        if res.get("ok"):
            return dict(res, how="refreshed silently")
        return dict(browser_login(_settings, headless=False, timeout_s=timeout_seconds), how="interactive sign-in")
    return await _run(go)


@mcp.tool()
async def bb_status() -> dict:
    """Which Blackboard and account this is, where files download to, and when the last sync ran."""
    def go():
        last = Syncer(_settings, _bb()).state.get("last_sync")
        me = _bb().me()
        return {"base_url": _settings.base_url, "signed_in_as": me.get("userName"),
                "name": (me.get("name") or {}).get("given"), "download_dir": str(_settings.download_dir),
                "last_sync": datetime.fromtimestamp(last).isoformat(timespec="minutes") if last else None}
    return await _run(go)


@mcp.tool()
async def bb_courses(include_all: bool = False) -> list[dict] | dict:
    """List current Blackboard courses (include_all=True: every course and organisation you're enrolled in)."""
    def go():
        bb = _bb()
        cs = bb.courses(include_organisations=True) if include_all else Syncer(_settings, bb).courses()
        return [{"id": c.id, "course_id": c.course_id, "code": c.code, "name": c.name,
                 "last_accessed": c.last_accessed, "url": c.url} for c in cs]
    return await _run(go)


@mcp.tool()
async def bb_browse(course: str, folder_id: str | None = None) -> dict:
    """List the content in a course (or inside one folder): titles, types, text, links and grade columns.
    `course` can be a course code, part of its name, or its id."""
    def go():
        bb = _bb()
        c = bb.find_course(course)
        items = [{
            "id": it["id"], "title": it.get("title"), "type": handler_id(it),
            "has_children": it.get("hasChildren", False), "modified": it.get("modified"),
            "text": html_to_text(it.get("body") or it.get("description"))[:600],
            "links": [l["url"] for l in body_links(it.get("body"), _settings.base_url)][:10],
            "grade_column": (it.get("contentHandler") or {}).get("gradeColumnId"),
            "open_in_blackboard": bb.web_link(c, it),
        } for it in bb.contents(c.id, folder_id)]
        return {"course": c.short_name(), "folder_id": folder_id, "items": items}
    return await _run(go)


@mcp.tool()
async def bb_download(course: str, content_id: str) -> dict:
    """Download every file attached to (or embedded in) one content item. Returns the local paths."""
    def go():
        bb = _bb()
        c = bb.find_course(course)
        folder = _settings.download_dir / safe(c.short_name(), 60) / "Downloads"
        paths = []
        for att in bb.attachments(c.id, content_id):
            dest = folder / safe(att.get("fileName") or att["id"], 120)
            bb.download(bb.attachment_url(c.id, content_id, att["id"]), dest)
            paths.append(str(dest))
        item = bb.get(f"/learn/api/public/v1/courses/{c.id}/contents/{content_id}")
        for ln in body_links(item.get("body"), _settings.base_url):
            if ln["blackboard_file"] and not ln.get("inline_image"):
                dest = folder / safe(ln["text"], 120)
                bb.download(ln["url"], dest)
                paths.append(str(dest))
        return {"title": item.get("title"), "files": paths}
    return await _run(go)


@mcp.tool()
async def bb_upcoming(days: int = 21) -> dict:
    """Due dates from Blackboard for the next `days` days (assignments, quizzes, Turnitin)."""
    def go():
        bb = _bb()
        now = datetime.now(timezone.utc)
        names = {c.id: c.short_name() for c in bb.courses(include_organisations=True)}
        items = [{"course": names.get(it.get("calendarId"), it.get("calendarName")), "title": it.get("title"),
                  "due": it.get("end") or it.get("start"), "details": html_to_text(it.get("description"))[:400]}
                 for it in bb.calendar_due(now - timedelta(days=1), now + timedelta(days=days))]
        items.sort(key=lambda i: i["due"] or "")
        return {"window_days": days, "items": items}
    return await _run(go)


@mcp.tool()
async def bb_announcements(course: str | None = None, days: int = 14) -> dict:
    """Recent announcements for one course, or for all current courses if none is given."""
    def go():
        bb = _bb()
        cs = [bb.find_course(course)] if course else Syncer(_settings, bb).courses()
        since = datetime.now(timezone.utc) - timedelta(days=days)
        out = []
        for c in cs:
            for a in bb.announcements(c.id):
                when = parse_dt(a.get("created"))
                if when and when < since:
                    continue
                out.append({"course": c.short_name(), "title": a.get("title"), "posted": a.get("created"),
                            "text": html_to_text(a.get("body"))[:1500]})
        out.sort(key=lambda a: a["posted"] or "", reverse=True)
        return {"days": days, "announcements": out}
    return await _run(go)


def _sync_worker(courses):
    try:
        _job["report"] = Syncer(_settings, _bb(), lambda m: _job.update(progress=m)).run(courses or None)
    except LoginRequired as e:
        _job["report"] = {"login_required": True, "message": str(e)}
    except Exception as e:  # noqa: BLE001 - surfaced through bb_sync_status
        _job["report"] = {"error": f"{type(e).__name__}: {e}"}
    finally:
        _job["running"] = False


@mcp.tool()
async def bb_sync(courses: list[str] | None = None, wait_seconds: int = 20) -> dict:
    """Download the PDFs (slides, readings, worksheets) from every current course, or just `courses`, into
    <download folder>/<course>/<week>/ (SlideMate's library if it's set up). Only new or changed files are
    fetched. Runs in the background: if it isn't done within wait_seconds, call bb_sync_status."""
    with _job_lock:
        if not _job.get("running"):
            _job.clear()
            _job.update(running=True, started_at=time.time(), progress="Finding your courses…", report=None)
            threading.Thread(target=_sync_worker, args=(courses,), daemon=True).start()
    deadline = time.time() + max(0, wait_seconds)
    while _job.get("running") and time.time() < deadline:
        await anyio.sleep(0.5)
    return await bb_sync_status()


@mcp.tool()
async def bb_sync_status() -> dict:
    """Progress (while running) or the result of the most recent bb_sync."""
    if _job.get("running"):
        return {"running": True, "progress": _job.get("progress"),
                "elapsed_s": round(time.time() - _job.get("started_at", time.time()))}
    return {"running": False, "report": _job.get("report")}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
