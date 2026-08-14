from __future__ import annotations

import argparse
from pathlib import Path

from fpga_demo_platform.api import app_from_paths
from fpga_demo_platform.demos import list_demos

DEFAULT_DB = Path("state/sessions.sqlite3")
DEFAULT_ARTIFACTS = Path("state/session-artifacts")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fpga-demo")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--artifacts", type=Path, default=DEFAULT_ARTIFACTS)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List runnable demo definitions used internally by projects")

    serve_p = sub.add_parser("serve", help="Start the FPGA API server")
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=9118)

    args = parser.parse_args(argv)

    if args.command == "list":
        for demo in list_demos():
            print(f"{demo.id}\t{demo.board}\t{demo.kind}\t{demo.name}")
        return 0


    if args.command == "serve":
        import uvicorn

        app = app_from_paths(args.db, args.artifacts)
        uvicorn.run(app, host=args.host, port=args.port)
        return 0

    return 2

if __name__ == "__main__":
    raise SystemExit(main())
