"""Thin client for the Blackboard Learn public REST API, authenticated with the
student's own browser session cookies (the same calls the Ultra web UI makes).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Iterator
from urllib.parse import unquote, urljoin

import httpx
from bs4 import BeautifulSoup

from .auth import LoginRequired, load_cookies, refresh_silently
from .config import Settings

# A unit code inside a course id or name, e.g. PHIL20069 in "PHIL20069_2026_TB-1" (Bristol) or EC100 / MY452.
UNIT_CODE = re.compile(r"(?<![A-Z0-9])([A-Z]{2,5}\d{3,5})(?!\d)")
API = "/learn/api/public"


def unit_code(*texts: str | None) -> str | None:
    for t in texts:
        if t:
            m = UNIT_CODE.search(t.upper())
            if m:
                return m.group(1)
    return None


def parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def handler_id(item: dict) -> str:
    return ((item.get("contentHandler") or {}).get("id") or "").replace("resource/", "")


def html_to_text(html: str | None) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    blocks = [el.get_text(" ", strip=True) for el in soup.find_all(["p", "li", "h1", "h2", "h3", "h4", "div"])
              if not el.find(["p", "li", "div"])]
    text = "\n".join(b for b in blocks if b) or soup.get_text("\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def body_links(html: str | None, base_url: str) -> list[dict]:
    """Links and embedded files inside an Ultra Document/description body."""
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for tag, attr in (("a", "href"), ("img", "src")):
        for el in soup.find_all(tag):
            href = el.get(attr)
            if not href or href.startswith(("mailto:", "#", "data:")):
                continue
            href = urljoin(base_url + "/", href)
            if href in seen:
                continue
            seen.add(href)
            internal = "bbcswebdav" in href or "/bbcswebdav/" in href
            name, is_image = None, tag == "img"
            if el.get("data-bbfile"):
                try:
                    meta = json.loads(el["data-bbfile"])
                    name = meta.get("fileName") or meta.get("linkName")
                    # Ultra embeds pictures as <a data-bbfile='{"mimeType":"image/jpeg",…}'>
                    is_image = is_image or str(meta.get("mimeType", "")).startswith("image/")
                except (ValueError, AttributeError):
                    pass
            name = name or el.get_text(strip=True) or unquote(href.split("?")[0].rsplit("/", 1)[-1])
            out.append({"url": href, "text": name, "blackboard_file": internal, "inline_image": is_image})
    return out


@dataclass
class Course:
    id: str                 # internal primary key, e.g. _12345_1
    course_id: str          # Blackboard "courseId", e.g. SEMT20003_2026_TB-1
    name: str
    code: str | None        # unit code, e.g. SEMT20003
    external_id: str | None = None
    term: str | None = None
    last_accessed: str | None = None
    url: str = ""
    raw: dict = field(default_factory=dict, repr=False)

    def short_name(self) -> str:
        name = " ".join(self.name.split())
        return name if not self.code or self.code in name else f"{self.code} {name}"


class Blackboard:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None,
                 refresher: Callable[[Settings], bool] | None = refresh_silently):
        self.s = settings
        self._transport = transport
        self._refresher = refresher
        self._client = self._new_client()
        self._me: dict | None = None

    def _new_client(self) -> httpx.Client:
        return httpx.Client(base_url=self.s.base_url, cookies=load_cookies(self.s), transport=self._transport,
                            follow_redirects=True, timeout=httpx.Timeout(30, read=120),
                            headers={"Accept": "application/json", "User-Agent": "blackboard-mcp/0.1 (+https://github.com/Mattlo0546/blackboard-mcp)"})

    # -- low level -------------------------------------------------------
    def _request(self, method: str, url: str, *, stream: bool = False, retry_auth: bool = True, **kw) -> httpx.Response:
        if not self._client.cookies:
            if not (self._refresher and self._refresher(self.s)):
                raise LoginRequired()
            self._client = self._new_client()
        req = self._client.build_request(method, url, **kw)
        r = self._client.send(req, stream=stream)
        # An expired session shows up as 401, as a redirect to the SSO login page, or (when another
        # process has just refreshed the session) as 403/404 on /users/me, which always exists when signed in.
        expired = r.status_code == 401 or (r.status_code in (403, 404) and url.rstrip("/").endswith("/users/me")) or (
            r.status_code == 200 and "text/html" in r.headers.get("content-type", "")
            and url.startswith(API) and ("login" in str(r.url).lower() or "sso" in str(r.url).lower()))
        if expired:
            r.close()
            if retry_auth and self._refresher and self._refresher(self.s):
                self._client = self._new_client()
                return self._request(method, url, stream=stream, retry_auth=False, **kw)
            raise LoginRequired()
        return r

    def get(self, path: str, **params) -> Any:
        params = {k: v for k, v in params.items() if v is not None}
        # Note: passing an empty params dict makes httpx drop the query string of
        # `path`, which would break Blackboard's `nextPage` links.
        r = self._request("GET", path, **({"params": params} if params else {}))
        if r.status_code in (403, 404):
            raise PermissionError(f"{r.status_code} for {path}")
        r.raise_for_status()
        return r.json()

    def paged(self, path: str, **params) -> Iterator[dict]:
        params.setdefault("limit", 100)
        data = self.get(path, **params)
        seen: set[str] = set()
        while True:
            yield from data.get("results", [])
            nxt = (data.get("paging") or {}).get("nextPage")
            if not nxt or nxt in seen or len(seen) > 200:
                return
            seen.add(nxt)
            data = self.get(nxt)

    # -- users / courses --------------------------------------------------
    def me(self) -> dict:
        if self._me is None:
            self._me = self.get(f"{API}/v1/users/me")
        return self._me

    def courses(self, include_organisations: bool = False) -> list[Course]:
        uid = self.me()["id"]
        out = []
        for m in self.paged(f"{API}/v1/users/{uid}/courses", expand="course"):
            c = m.get("course")
            if c is None:
                try:
                    c = self.get(f"{API}/v3/courses/{m['courseId']}")
                except PermissionError:
                    continue
            if not include_organisations and c.get("organization"):
                continue
            avail = (c.get("availability") or {}).get("available")
            if avail == "No":
                continue
            out.append(Course(
                id=c["id"], course_id=c.get("courseId", ""), name=c.get("name", ""),
                code=unit_code(c.get("courseId"), c.get("name"), c.get("externalId")),
                external_id=c.get("externalId"), term=c.get("termId"),
                last_accessed=m.get("lastAccessed"),
                url=c.get("externalAccessUrl") or f"{self.s.base_url}/ultra/courses/{c['id']}/outline",
                raw=c))
        out.sort(key=lambda c: c.last_accessed or "", reverse=True)
        return out

    def find_course(self, query: str, courses: list[Course] | None = None) -> Course:
        courses = courses or self.courses(include_organisations=True)
        q = query.strip().lower()
        for c in courses:
            if q in (c.id.lower(), c.course_id.lower(), (c.code or "").lower()):
                return c
        matches = [c for c in courses if q in c.name.lower() or q in c.course_id.lower()]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise ValueError(f"No Blackboard course matches '{query}'.")
        # prefer the most recently accessed
        return matches[0]

    # -- content ----------------------------------------------------------
    def contents(self, course_pk: str, parent_id: str | None = None) -> list[dict]:
        path = f"{API}/v1/courses/{course_pk}/contents" + (f"/{parent_id}/children" if parent_id else "")
        try:
            return list(self.paged(path))
        except PermissionError:
            return []

    def walk(self, course_pk: str, parent_id: str | None = None, trail: tuple[str, ...] = (),
             max_depth: int = 8) -> Iterator[tuple[tuple[str, ...], dict]]:
        """Yield (folder trail, item) for every visible content item in a course."""
        for item in sorted(self.contents(course_pk, parent_id), key=lambda i: i.get("position", 0)):
            if (item.get("availability") or {}).get("available") == "No":
                continue
            yield trail, item
            if item.get("hasChildren") and len(trail) < max_depth:
                yield from self.walk(course_pk, item["id"], trail + (item.get("title") or "Untitled",), max_depth)

    def attachments(self, course_pk: str, content_id: str) -> list[dict]:
        try:
            return list(self.paged(f"{API}/v1/courses/{course_pk}/contents/{content_id}/attachments"))
        except (PermissionError, httpx.HTTPStatusError):
            return []

    def download(self, url: str, dest, *, max_mb: float = 300) -> tuple[str, str]:
        """Stream a file to `dest` (a pathlib.Path). Returns (path, content_type)."""
        r = self._request("GET", url, stream=True)
        try:
            if r.status_code >= 400:
                raise PermissionError(f"{r.status_code} downloading {url}")
            ctype = r.headers.get("content-type", "application/octet-stream").split(";")[0]
            size = int(r.headers.get("content-length") or 0)
            if size and size > max_mb * 1024 * 1024:
                raise ValueError(f"file too large ({size/1e6:.0f} MB)")
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(dest.suffix + ".part")
            with open(tmp, "wb") as fh:
                for chunk in r.iter_bytes(1 << 16):
                    fh.write(chunk)
            tmp.replace(dest)
            return str(dest), ctype
        finally:
            r.close()

    def attachment_url(self, course_pk: str, content_id: str, att_id: str) -> str:
        return f"{API}/v1/courses/{course_pk}/contents/{content_id}/attachments/{att_id}/download"

    # -- deadlines --------------------------------------------------------
    def gradebook_columns(self, course_pk: str) -> list[dict]:
        try:
            return list(self.paged(f"{API}/v2/courses/{course_pk}/gradebook/columns"))
        except (PermissionError, httpx.HTTPStatusError):
            return []

    def calendar_due(self, since: datetime, until: datetime) -> list[dict]:
        """Due dates across all courses (gradebook columns on the calendar)."""
        items: list[dict] = []
        # The API caps the window at 16 weeks per request.
        start = since
        while start < until:
            end = min(until, start + timedelta(days=110))
            try:
                items += list(self.paged(f"{API}/v1/calendars/items", type="GradebookColumn",
                                         since=start.isoformat(), until=end.isoformat()))
            except (PermissionError, httpx.HTTPStatusError):
                break
            start = end
        return items

    def announcements(self, course_pk: str) -> list[dict]:
        try:
            return list(self.paged(f"{API}/v1/courses/{course_pk}/announcements"))
        except (PermissionError, httpx.HTTPStatusError):
            return []

    def web_link(self, course: Course, item: dict | None = None) -> str:
        if item:
            for link in item.get("links") or []:
                if link.get("type") == "text/html" and link.get("href"):
                    return urljoin(self.s.base_url, link["href"])
        return course.url
