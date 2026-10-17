"""Command line: `blackboard-mcp login | status | courses | sync [COURSE…] | serve`."""
from __future__ import annotations

import argparse
import json
import sys


def main() -> None:
    p = argparse.ArgumentParser(prog="blackboard-mcp", description="Blackboard Learn (Ultra) MCP server")
    sub = p.add_subparsers(dest="cmd")
    sp = sub.add_parser("login", help="sign in (opens Chrome)")
    sp.add_argument("--timeout", type=int, default=300)
    sub.add_parser("status", help="who you're signed in as")
    sub.add_parser("courses", help="your current courses")
    sp = sub.add_parser("sync", help="download PDFs from every current course (or the ones named)")
    sp.add_argument("courses", nargs="*")
    sub.add_parser("serve", help="run the MCP server on stdio (the default)")
    args = p.parse_args()
    if args.cmd in (None, "serve"):
        from .server import main as serve
        serve()
        return

    import anyio
    from . import server
    if args.cmd == "login":
        rep = anyio.run(lambda: server.bb_login(args.timeout))
    elif args.cmd == "status":
        rep = anyio.run(server.bb_status)
    elif args.cmd == "courses":
        rep = anyio.run(server.bb_courses)
        if isinstance(rep, list):
            for c in rep:
                print(f"  {c['code'] or '':<12} {c['name']}")
            sys.exit(0)
    else:
        rep = anyio.run(lambda: server.bb_sync(args.courses or None, 0))
        last = None
        while rep.get("running"):
            if rep.get("progress") != last:
                print(rep.get("progress"), flush=True)
                last = rep.get("progress")
            import time
            time.sleep(1)
            rep = anyio.run(server.bb_sync_status)
        rep = rep.get("report") or rep
    print(json.dumps(rep, indent=1))
    sys.exit(2 if rep.get("login_required") else 1 if rep.get("error") or rep.get("ok") is False else 0)


if __name__ == "__main__":
    main()
