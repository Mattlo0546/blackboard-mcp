# Blackboard MCP Server: Blackboard Learn for Claude, ChatGPT Codex and Cursor

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-server-8A2BE2)](https://modelcontextprotocol.io)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)

**blackboard-mcp** is an open-source [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server for
**Blackboard Learn** (Ultra). It lets AI assistants (Claude Desktop, Claude Code, ChatGPT Codex, Cursor, VS Code and
[SlideMate](https://github.com/Mattlo0546/slidemate)) read a student's Blackboard courses, content, deadlines and
announcements. It can also **download this year's lecture slides and readings** into one folder per course.

- **Works at any university that uses Blackboard**, including Imperial College London, Edinburgh, Bristol, Leeds
  and Southampton ([list](#universities-that-use-blackboard)). Set `BB_BASE_URL` to yours.
- **No API key needed.** It uses Blackboard's REST API with your own browser session. You sign in through your
  university's normal SSO and MFA in a real browser window.
- **Read-only.** It can't submit work, post or change anything on Blackboard.

> Using Canvas or Moodle instead? See [canvas-mcp](https://github.com/Mattlo0546/canvas-mcp) (Oxford, Harvard,
> Stanford…) and [moodle-mcp](https://github.com/Mattlo0546/moodle-mcp) (UCL, King's, LSE, Cambridge…).

## What you can ask

- *"What's due on Blackboard in the next three weeks?"*
- *"Any new announcements in my courses?"*
- *"Download this year's lecture slides."*

## Install

**With SlideMate:** Settings → **Your university** → pick your university (or Blackboard and your address) → **Connect**. SlideMate
installs this, opens the sign-in window, and pulls your slides. Nothing else to do.

**By hand (macOS, one command).** It installs [uv](https://docs.astral.sh/uv/) (which brings its own Python), then
this, then opens Chrome so you can sign in once. Replace the address with your university's:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh && ~/.local/bin/uv tool install --managed-python https://github.com/Mattlo0546/blackboard-mcp/archive/refs/heads/main.zip && BB_BASE_URL=https://www.ole.bris.ac.uk ~/.local/bin/blackboard-mcp login
```

Then add it to your MCP client with the same `BB_BASE_URL` in its environment:

```bash
claude mcp add blackboard -e BB_BASE_URL=https://www.ole.bris.ac.uk -- ~/.local/bin/blackboard-mcp serve
```

## Tools

| Tool | What it does |
| --- | --- |
| `bb_login` | Opens a browser for the university sign-in and saves the session. Tries a silent refresh first. |
| `bb_status` | Who you're signed in as, which site, where files download to, last sync |
| `bb_courses` | This year's courses (`include_all` for every course and organisation) |
| `bb_browse` | A course's content (or one folder's): titles, text, links, grade columns |
| `bb_download` | Every file in one content item |
| `bb_upcoming` | Due dates in the next N days (default 21) |
| `bb_announcements` | Recent announcements, for one course or all of this year's |
| `bb_sync` / `bb_sync_status` | Download the PDFs from this year's courses (or the ones named), in the background |

**This year's courses:** students stay enrolled in years of old courses, so a sync only takes courses whose end date is
still ahead, or (as Blackboard rarely sets end dates) that were created within about 9 months of your newest course.
Files land in `<folder>/<course>/<Week NN or top-level folder>/`, and only new or changed ones are downloaded.

## Connect it to your AI app

### Claude Desktop

Settings → Developer → Edit Config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "blackboard": {
      "command": "/Users/YOU/.local/bin/blackboard-mcp",
      "args": ["serve"],
      "env": { "BB_BASE_URL": "https://bb.imperial.ac.uk" }
    }
  }
}
```

The same block works in Cursor (`~/.cursor/mcp.json`). VS Code's `.vscode/mcp.json` uses `"servers"` in place of
`"mcpServers"`.

### ChatGPT Codex CLI

```bash
codex mcp add blackboard --env BB_BASE_URL=https://bb.imperial.ac.uk -- ~/.local/bin/blackboard-mcp serve
```

## Universities that use Blackboard

These addresses were checked to be Blackboard Learn sites:

| University | `BB_BASE_URL` |
| --- | --- |
| Imperial College London | `bb.imperial.ac.uk` |
| University of Edinburgh (Learn) | `www.learn.ed.ac.uk` |
| University of Bristol | `www.ole.bris.ac.uk` |
| University of Leeds (Minerva) | `minerva.leeds.ac.uk` |
| University of Sheffield | `vle.shef.ac.uk` |
| University of Southampton | `blackboard.soton.ac.uk` |
| University of York (Yorkshare) | `vle.york.ac.uk` |

Your university's address is the one in your browser's address bar when you open Blackboard. If its landing page has
an unusual sign-in button, set `BB_SSO_BUTTON` to that button's text.

## Settings (all optional except the address)

Environment variables win over `~/.blackboard-mcp/config.json`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `BB_BASE_URL` | none | Your university's Blackboard address |
| `BB_DOWNLOAD_DIR` | SlideMate's first slides folder, else `~/BlackboardFiles` | Where synced files go |
| `BB_BROWSER_CHANNEL` | `chrome` | Browser for sign-in; `""` uses Playwright's own Chromium |
| `BB_SSO_BUTTON` | a few common ones | Text of the button that starts single sign-on on your Blackboard's landing page |
| `BB_MCP_HOME` | `~/.blackboard-mcp` | Where the session cookies, sign-in browser profile and sync state live |

## FAQ

**Is there an MCP server for Imperial's or Edinburgh's Blackboard?**
Yes, this one. Set `BB_BASE_URL` to `bb.imperial.ac.uk` or `www.learn.ed.ac.uk`. In SlideMate, pick the university
from the list.

**Do I need a Blackboard API key or developer account?**
No. It uses the same REST API the Blackboard website uses, with your own signed-in session.

**Does it work with ChatGPT?**
It works with OpenAI's Codex CLI and with any app that supports local (stdio) MCP servers. The ChatGPT website can
only use remote MCP servers.

## Privacy

- **Access:** read-only. It can't submit work, post or change anything on Blackboard.
- **Storage:** the session cookies stay on your computer (`~/.blackboard-mcp/cookies.json`, readable only by you).
  Delete the folder to sign out. Data goes directly between your computer and your university's Blackboard.

## Development

```bash
uv run --with pytest pytest     # offline tests: which courses count as this year's, file layout, MCP over stdio
```

## Related

- [canvas-mcp](https://github.com/Mattlo0546/canvas-mcp): MCP server for Canvas LMS
- [moodle-mcp](https://github.com/Mattlo0546/moodle-mcp): MCP server for Moodle
- [classroom-mcp](https://github.com/Mattlo0546/classroom-mcp): MCP server for Google Classroom
- [SlideMate](https://github.com/Mattlo0546/slidemate): a free Mac app with an AI tutor that has read your whole
  lecture deck. It sets all of these up in one click.

MIT licensed. Not affiliated with Anthology Inc. or any university. Blackboard is a trademark of Anthology Inc.
