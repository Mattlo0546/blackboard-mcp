"""Download the PDFs (lecture slides, readings, worksheets) from your current Blackboard courses.

Layout: <download folder>/<course>/<Week NN or top-level folder>/<file>.pdf. Each file is fetched once: the
item's "modified" time is remembered, so later syncs only download what's new or changed. Pages that are
noise for studying (welcome, help, forums, recordings) are skipped, and so are sites that aren't courses and files
that aren't for studying, such as posters, handbooks and forms (relevance.py).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from . import relevance
from .auth import LoginRequired
from .bb import Blackboard, Course, body_links, handler_id, parse_dt
from .config import Settings

FOLDERISH = {"x-bb-folder", "x-bb-lesson", "x-bb-module-page"}
DOC_BODY = "ultraDocumentBody"  # Ultra stores a Document as a folder + a child holding the body
NOISE = re.compile(r"welcome|help for students|help and support|contacts?\b|communication|re/?play|panopto|echo ?360|"
                   r"discussion|general questions|forum|student (support|voice)|announcements?", re.I)
WEEK = [re.compile(r"(?<![a-z])week[\s_:-]*(\d{1,2})(?!\d)", re.I),
        re.compile(r"(?<![a-z])(?:lecture|teaching|session|topic)[\s_-]*(\d{1,2})(?!\d)", re.I)]
YEAR_WINDOW = timedelta(days=270)  # courses created within ~9 months of your newest one count as this year's


def safe(name: str, maxlen: int = 80) -> str:
    name = re.sub(r"\s*:\s*", " - ", name or "Untitled")
    name = re.sub(r'[\\/*?"<>|\x00-\x1f]+', "_", name).strip(" .")
    return (name or "Untitled")[:maxlen]


def parse_week(*texts: str | None) -> int | None:
    for t in texts:
        for pat in WEEK:
            m = pat.search(t or "")
            if m and 0 < int(m.group(1)) <= 24:
                return int(m.group(1))
    return None


def current_courses(courses: list[Course], now: datetime) -> list[Course]:
    """This year's courses. Students stay enrolled in years of old courses, and a full sync shouldn't fill the
    disk with them. Blackboard rarely sets end dates (and "last accessed" changes whenever the API is used), so
    a course counts as current if its end date is still ahead, or, without one, if it was created within ~9
    months of your newest course (each year's courses are created together, before the year starts)."""
    def created(c):
        return parse_dt(c.raw.get("created"))
    newest = max((t for t in map(created, courses) if t), default=None)
    out = []
    for c in courses:
        end = parse_dt(((c.raw.get("availability") or {}).get("duration") or {}).get("end"))
        if end:
            keep = end > now
        else:
            t = created(c)
            keep = not t or not newest or newest - t <= YEAR_WINDOW
        if keep:
            out.append(c)
    return out


class Syncer:
    def __init__(self, settings: Settings, bb: Blackboard, progress: Callable[[str], None] = lambda m: None):
        self.s, self.bb, self.progress = settings, bb, progress
        try:
            self.state = json.loads(settings.state_path.read_text())
        except (OSError, ValueError):
            self.state = {}
        self.state.setdefault("files", {})

    def save(self) -> None:
        self.s.state_path.write_text(json.dumps(self.state, indent=1))

    def courses(self) -> list[Course]:
        return current_courses(self.bb.courses(), datetime.now(timezone.utc))

    @property
    def prefs_path(self) -> Path:
        return self.s.home / "courses.json"

    def prefs(self) -> dict:
        try:
            return json.loads(self.prefs_path.read_text())
        except (OSError, ValueError):
            return {}

    def choose(self, courses: list[Course]) -> tuple[list[Course], list[dict]]:
        """(courses a full sync pulls, [{id, name, why}] for the ones it skips)."""
        by_id = {c.id: c for c in courses}
        keep, skipped = relevance.choose([{"id": c.id, "name": c.name, "shortname": c.course_id,
                                           "idnumber": c.external_id or ""} for c in courses], self.prefs())
        return [by_id[k["id"]] for k in keep], [{"id": s["id"], "name": s["name"], "why": s["why"]} for s in skipped]

    def run(self, only: list[str] | None = None) -> dict:
        passed: list[dict] = []
        if only:
            courses = [self.bb.find_course(q) for q in only]
        else:
            courses, passed = self.choose(self.courses())
        reports = []
        try:
            for i, c in enumerate(courses, 1):
                self.progress(f"Course {i} of {len(courses)}: {c.short_name()}…")
                reports.append(self.sync_course(c))
                self.save()
        finally:
            self.state["last_sync"] = time.time()
            self.save()
        new = sum(r["downloaded"] for r in reports)
        errors = [f"{r['course']}: {e}" for r in reports for e in r["errors"]]
        where = str(self.s.download_dir).replace(str(Path.home()), "~", 1)
        summary = (f"{new} new PDF{'s' if new != 1 else ''} from {len(courses)} course{'s' if len(courses) != 1 else ''}"
                   f" into {where}" + (f" ({len(errors)} couldn't be downloaded)" if errors else "") + "."
                   + (f" Skipped {len(passed)} site{'s' if len(passed) != 1 else ''} that aren't courses"
                      f" ({', '.join(p['name'] for p in passed[:3])}{'…' if len(passed) > 3 else ''})." if passed else ""))
        return {"summary": summary, "folder": str(self.s.download_dir), "downloaded": new, "courses": reports,
                "errors": errors, "not_study_files": sum(r.get("not_study", 0) for r in reports),
                "skipped_courses": passed}

    def sync_course(self, c: Course) -> dict:
        root = self.s.download_dir / safe(c.short_name(), 60)
        downloaded, skipped, errors, noise = [], 0, [], 0
        for trail, item in self.bb.walk(c.id):
            if item.get("title") == DOC_BODY:
                item, trail = dict(item, title=trail[-1] if trail else "Document"), trail[:-1]
            elif handler_id(item) in FOLDERISH and not item.get("body"):
                continue
            title = item.get("title") or ""
            if NOISE.search(title) or any(NOISE.search(t) for t in trail) or \
                    not all(relevance.is_study_section(t) for t in trail[:1]):
                continue
            week = parse_week(title, *reversed(trail))
            folder = root / (f"Week {week:02d}" if week else safe(trail[0], 60) if trail else "Other")
            modified = item.get("modified") or item.get("created") or ""
            for key, name, url in self.files(c, item):
                if not relevance.is_study_file(name, title, *trail):
                    noise += 1  # a poster, handbook or form
                    continue
                dest = folder / name
                if self.state["files"].get(key) == modified and dest.exists():
                    skipped += 1
                    continue
                try:
                    self.bb.download(url, dest)
                    self.state["files"][key] = modified
                    downloaded.append(str(dest))
                except LoginRequired:
                    raise
                except Exception as e:  # noqa: BLE001 - report per file, keep going
                    errors.append(f"{name}: {e}")
        return {"course": c.short_name(), "folder": str(root), "downloaded": len(downloaded), "skipped": skipped,
                "not_study": noise, "files": downloaded, "errors": errors}

    def files(self, c: Course, item: dict):
        """(state key, file name, download URL) for each PDF attached to or embedded in an item."""
        seen = set()
        for att in self.bb.attachments(c.id, item["id"]):
            name = safe(att.get("fileName") or item.get("title") or "file", 120)
            if name.lower().endswith(".pdf") and name not in seen:
                seen.add(name)
                yield f"{c.id}:{item['id']}:{att['id']}", name, self.bb.attachment_url(c.id, item["id"], att["id"])
        for ln in body_links(item.get("body"), self.s.base_url):
            if not ln["blackboard_file"] or ln.get("inline_image"):
                continue
            name = safe(ln["text"], 120)
            if "." not in name[-6:]:
                name += Path(ln["url"].split("?")[0]).suffix
            if name.lower().endswith(".pdf") and name not in seen:
                seen.add(name)
                yield f"{c.id}:{item['id']}:{hashlib.sha1(ln['url'].encode()).hexdigest()[:12]}", name, ln["url"]
