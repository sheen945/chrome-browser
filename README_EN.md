# chrome-browser

> The single browser automation skill for this machine: a persistent Chrome instance with a fixed login profile and a CDP debugging port handles every browser task.

## Overview

chrome-browser is a WorkBuddy / Claude Code skill that provides the one and only sanctioned channel for all browser automation on this machine: opening pages, taking screenshots, scraping dynamic content, working with logged-in sessions, posting, admin consoles, ad campaigns, verifying production pages — everything goes through this skill. Alternative browser setups (Playwright-launched instances, agent-browser, edge-browser, etc.) are explicitly off-limits.

The core problem it solves: **browsers launched from inside the AI agent's sandbox get reaped by the OS when the command finishes** (the Windows job object mechanism), so login state and debug connections cannot survive. This skill combines three pieces — launching Chrome indirectly through the desktop shell, a fixed user-data directory, and a CDP debugging port — so the browser stays alive indefinitely, logins persist permanently, and the agent can attach at any time.

Best suited for: WorkBuddy / Claude Code users doing browser automation on a Windows workstation, especially workflows that need persistent website logins, repeated page scraping, or operations in various web admin consoles.

## Features

- **Single-channel policy**: every browser operation goes through this skill's Google Chrome instance, preventing multiple browser setups from fighting each other and fragmenting login state.
- **Persistent browser mechanism**: Chrome is launched indirectly via `explorer.exe` (parented to the desktop shell rather than the sandbox process), so it is never reaped when an agent command ends and can stay running forever.
- **Automatic port fallback**: the debug port prefers 9222 and falls back to 9233, then 9244 when occupied (WorkBuddy.exe itself is known to listen on 127.0.0.1:9222, so this fallback is mandatory).
- **Fixed profile directory**: the user-data directory is pinned to `C:\Users\Administrator\WorkBuddy\chrome-cdp-profile`, so cookies and login state survive restarts — log in once, stay logged in.
- **Playwright takeover**: the agent attaches to the already-running Chrome via `playwright.chromium.connect_over_cdp()`, reusing existing tabs and sessions.
- **One-command health check**: `scripts/chrome_browser.py` probes ports, launches the instance if needed, and verifies the connection.
- **Generic page scraper**: `scripts/scrape.py` connects to the persistent Chrome, opens a URL, checks login state, runs your custom JS extraction script, and writes JSON + CSV output (utf-8-sig, opens cleanly in Excel).
- **Login-expiry guard**: during scraping, the tool detects redirects to login pages (matching markers like login / signin / 登录 / 验证身份 / passport). On a hit it writes an alert log, skips saving data for that run, and exits with code 2 — a login page is never mistaken for real data.
- **Clear exit-code contract**: 0 success; 1 execution failure; 2 login expired (manual re-login required); 3 no debuggable browser available.

## How It Works / Tech Stack

- **Chrome DevTools Protocol (CDP)**: Chrome started with `--remote-debugging-port` exposes an HTTP debug interface (`/json/version`, etc.); Playwright attaches to the whole browser via `connect_over_cdp("http://127.0.0.1:<port>")`.
- **Windows process trees and sandbox reaping**: the agent sandbox runs inside a job object whose direct child processes are killed when the command exits; processes launched via `explorer.exe` are parented to the shell and immune to this reaping.
- **Detached process launch**: `launcher/chrome_launcher.py` starts Chrome with the `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP` flags and all stdio redirected to DEVNULL, fully decoupling it from the caller's lifecycle.
- **Tech stack**: Python 3, `playwright` (attach and drive), `requests` (CDP port probing), standard library only otherwise (socket / subprocess / ctypes / argparse / csv / json).

## Installation & Usage

### Install the skill

Copy the whole repository directory into your skills folder:

```bash
# WorkBuddy / CodeBuddy (user-level)
cp -r chrome-browser ~/.workbuddy/skills/

# or Claude Code
cp -r chrome-browser ~/.claude/skills/
```

For project-level use, copy it into the project's `.workbuddy/skills/` directory. Python dependencies: `pip install playwright requests`.

### Standard workflow

1. **Run the health-check script first** (probes ports, launches the instance if needed, verifies connectivity):

   ```bash
   python scripts/chrome_browser.py
   ```

2. **Attach with Playwright**:

   ```python
   from playwright.sync_api import sync_playwright

   with sync_playwright() as pw:
       browser = pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
       context = browser.contexts[0] if browser.contexts else browser.new_context()
       page = context.pages[0] if context.pages else context.new_page()
       page.goto("https://example.com")
       # ... drive the page ...
       # NEVER call browser.close() — the browser is persistent; closing it kills everything
   ```

3. **Scrape a page** (scrape.py):

   ```bash
   python scripts/scrape.py --url "<url>" --extract extract.js --out "<data dir>"
   python scripts/scrape.py --url "<url>" --extract extract.js --out data --name prices --wait 8
   python scripts/scrape.py --url "<url>" --extract extract.js --out data --login-marker "重新登录"
   ```

   Output layout: `<out>/<task name>/<YYYY-MM-DD>/data-<HHMMSS>.json` (machine-readable) + a matching `.csv` (human-readable) + `login-expiry.log` (login-expiry alerts).

### First-time setup

Log in to your target sites manually once inside the persistent Chrome (the profile directory is fixed, so sessions restore automatically next time). If you want a double-clickable desktop launcher, package `launcher/chrome_launcher.py` into an exe (see the build.txt note in that directory).

## Project Structure

```
chrome-browser/
├── SKILL.md                      # Skill definition (frontmatter + three iron rules + standard workflow)
├── README.md                     # Detailed Chinese README
├── README_EN.md                  # This file (detailed English README)
├── launcher/
│   └── chrome_launcher.py        # Persistent-browser launcher source (can be packaged as a desktop exe)
└── scripts/
    ├── chrome_browser.py         # Health check: port probing / instance launch / connection verification
    └── scrape.py                 # Generic scraper: login check + JS extraction + JSON/CSV output
```

## Notes & Caveats

- **Windows-only for now**: the Chrome path is hard-coded to `C:\Program Files\Google\Chrome\Application\chrome.exe` and the profile directory to `C:\Users\Administrator\WorkBuddy\chrome-cdp-profile`; adjust both when moving to another machine.
- **Never call `browser.close()`**: the browser is a shared persistent instance — closing it breaks every login session and all downstream tasks. Close only the pages you opened, or leave them open.
- **Port 9222 conflicts**: WorkBuddy.exe itself listens on 127.0.0.1:9222 and returns 401 — that is not Chrome. Always rely on the automatic fallback logic, and run the health-check script to learn the real port when connections fail.
- **No alternative setups**: do not use other browser skills (agent-browser / playwright-cli / edge-browser), do not create throwaway profiles, and do not invent your own debug-port conventions.
- **Handling expired logins**: when scrape.py exits with code 2, manually log in to the site once inside the persistent Chrome — do not try to scrape around a login wall.
- **Dependencies**: Google Chrome must be installed locally, and the Python environment needs `playwright` and `requests`.

## License

MIT

## Author

sheen945
