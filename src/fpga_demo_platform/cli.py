from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from fpga_demo_platform.api import app_from_paths
from fpga_demo_platform.demos import list_demos
from fpga_demo_platform.queue import JobQueue, job_to_dict

DEFAULT_DB = Path("state/jobs.sqlite3")
DEFAULT_RUNS = Path("runs")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fpga-demo")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--runs", type=Path, default=DEFAULT_RUNS)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List demos")

    run_p = sub.add_parser("run", help="Submit and immediately run one demo")
    run_p.add_argument("demo_id")
    run_p.add_argument("--input", default="{}", help="JSON object payload")

    sub.add_parser("worker-once", help="Run one queued job if available")

    serve_p = sub.add_parser("serve", help="Start FastAPI server")
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=9118)

    args = parser.parse_args(argv)
    queue = JobQueue(args.db, args.runs)

    if args.command == "list":
        for demo in list_demos():
            print(f"{demo.id}\t{demo.board}\t{demo.kind}\t{demo.name}")
        return 0

    if args.command == "run":
        payload = _parse_json_object(args.input)
        job = queue.submit(args.demo_id, payload, requester="cli")
        finished = queue.run_next()
        print(json.dumps(job_to_dict(finished or job), indent=2, sort_keys=True))
        return 0

    if args.command == "worker-once":
        job = queue.run_next()
        print(json.dumps(job_to_dict(job) if job else {"status": "idle"}, indent=2, sort_keys=True))
        return 0

    if args.command == "serve":
        import uvicorn

        app = app_from_paths(args.db, args.runs)
        uvicorn.run(app, host=args.host, port=args.port)
        return 0

    return 2


def _parse_json_object(text: str) -> dict[str, Any]:
    value = json.loads(text)
    if not isinstance(value, dict):
        raise SystemExit("--input must be a JSON object")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
