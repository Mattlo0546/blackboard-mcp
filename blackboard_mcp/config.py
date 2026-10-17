"""Settings, read from ~/.blackboard-mcp/config.json and environment variables.

Environment variables win over the file, so the MCP client config can set everything without editing files.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

HOME_DIR = Path(os.environ.get("BB_MCP_HOME", Path.home() / ".blackboard-mcp")).expanduser()


@dataclass
class Settings:
    # Your university's Blackboard, e.g. https://www.ole.bris.ac.uk or https://learn.example.ac.uk
    base_url: str = ""
    # Where synced files land: <root>/<course>/<week or folder>/. Unless set, that's SlideMate's library (its
    # first slides folder), so synced slides show up there; without SlideMate, ~/BlackboardFiles.
    download_dir: Path | None = None
    # The installed Google Chrome is used for the sign-in window; "" = Playwright's own Chromium.
    browser_channel: str = "chrome"
    # Text of the button that starts single sign-on on your Blackboard's landing page, if it has one
    # (only needed for the silent refresh; a few common ones are tried anyway).
    sso_button: str = ""
    home: Path = HOME_DIR

    @property
    def cookies_path(self) -> Path:
        return self.home / "cookies.json"

    @property
    def profile_dir(self) -> Path:
        return self.home / "browser-profile"

    @property
    def state_path(self) -> Path:
        return self.home / "sync-state.json"


def slidemate_library() -> Path | None:
    """The first slides folder in SlideMate's settings, if SlideMate is set up on this Mac."""
    data = Path(os.environ.get("SLIDEMATE_DATA") or Path.home() / "Library/Application Support/SlideMate")
    try:
        roots = json.loads((data / "config.json").read_text()).get("library_roots") or []
    except (OSError, ValueError):
        return None
    return next((Path(r).expanduser() for r in roots if r), None)


def normalise_url(url: str) -> str:
    """"learn.example.ac.uk/ultra/course" → "https://learn.example.ac.uk"."""
    url = (url or "").strip()
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    scheme, rest = url.split("://", 1)
    return f"{scheme}://{rest.split('/', 1)[0]}"


def load_settings() -> Settings:
    s = Settings()
    cfg_path = HOME_DIR / "config.json"
    if cfg_path.exists():
        for key, value in json.loads(cfg_path.read_text()).items():
            if key == "download_dir":
                s.download_dir = Path(value).expanduser()
            elif hasattr(s, key) and key != "home":
                setattr(s, key, value)
    env = os.environ
    if env.get("BB_BASE_URL"):
        s.base_url = env["BB_BASE_URL"]
    if env.get("BB_DOWNLOAD_DIR"):
        s.download_dir = Path(env["BB_DOWNLOAD_DIR"]).expanduser()
    if env.get("BB_BROWSER_CHANNEL") is not None:
        s.browser_channel = env["BB_BROWSER_CHANNEL"]
    if env.get("BB_SSO_BUTTON"):
        s.sso_button = env["BB_SSO_BUTTON"]
    s.base_url = normalise_url(s.base_url)
    if s.download_dir is None:
        s.download_dir = slidemate_library() or Path.home() / "BlackboardFiles"
    s.home.mkdir(parents=True, exist_ok=True)
    return s
