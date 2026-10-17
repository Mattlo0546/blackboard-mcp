# Blackboard MCP

An [MCP](https://modelcontextprotocol.io) server that gives AI tools ([SlideMate](https://github.com/Mattlo0546/slidemate),
Claude Desktop, Claude Code, Codex) read-only access to a student's **Blackboard Learn (Ultra)**: courses, content,
deadlines and announcements. It can also **download this year's lecture slides and readings** into one folder per
course.

It works with any university's Blackboard Ultra: set `BB_BASE_URL` to yours (e.g. `https://www.ole.bris.ac.uk`).
It uses Blackboard's REST API with your own browser session, and sign-in goes through your university's normal SSO + MFA
in a real browser window.

## Install

**With SlideMate:** Settings → **Your university** → Blackboard → enter your Blackboard address → **Connect**. SlideMate
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

## Settings (all optional except the address)

Environment variables win over `~/.blackboard-mcp/config.json`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `BB_BASE_URL` | none | Your university's Blackboard address |
| `BB_DOWNLOAD_DIR` | SlideMate's first slides folder, else `~/BlackboardFiles` | Where synced files go |
| `BB_BROWSER_CHANNEL` | `chrome` | Browser for sign-in; `""` uses Playwright's own Chromium |
| `BB_SSO_BUTTON` | a few common ones | Text of the button that starts single sign-on on your Blackboard's landing page |
| `BB_MCP_HOME` | `~/.blackboard-mcp` | Where the session cookies, sign-in browser profile and sync state live |

## Privacy

- **Access:** read-only. It can't submit work, post or change anything on Blackboard.
- **Storage:** the session cookies stay on your computer (`~/.blackboard-mcp/cookies.json`, readable only by you).
  Delete the folder to sign out. Data goes directly between your computer and your university's Blackboard.

## Development

```bash
uv run --with pytest pytest     # offline tests: which courses count as this year's, file layout, MCP over stdio
```

MIT licensed.
