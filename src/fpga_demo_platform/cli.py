from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any

from fpga_demo_platform.api import app_from_paths
from fpga_demo_platform.demos import get_demo, list_demos
from fpga_demo_platform.runners import run_demo

DEFAULT_DB = Path("state/sessions.sqlite3")
DEFAULT_RUNS = Path("runs")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fpga-demo")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--runs", type=Path, default=DEFAULT_RUNS)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List runnable demo definitions used internally by projects")

    run_p = sub.add_parser("run", help="Run one approved demo directly for hardware smoke testing")
    run_p.add_argument("demo_id")
    run_p.add_argument("--input", default="{}", help="JSON object payload")

    serve_p = sub.add_parser("serve", help="Start the FPGA API server")
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=9118)

    args = parser.parse_args(argv)

    if args.command == "list":
        for demo in list_demos():
            print(f"{demo.id}\t{demo.board}\t{demo.kind}\t{demo.name}")
        return 0

    if args.command == "run":
        payload = _parse_json_object(args.input)
        demo = get_demo(args.demo_id)
        validated = demo.validate_input(payload)
        artifact_dir = args.runs / uuid.uuid4().hex
        result = run_demo(demo, validated, artifact_dir)
        print(json.dumps({"demo_id": demo.id, "status": "succeeded", "result": result, "artifact_dir": str(artifact_dir)}, indent=2, sort_keys=True))
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
