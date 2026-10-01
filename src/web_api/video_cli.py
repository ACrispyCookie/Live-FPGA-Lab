from __future__ import annotations

import argparse

from .video import VideoConfig, VideoGate


def main() -> None:
    parser = argparse.ArgumentParser(description="Enable or disable the standalone FPGA video endpoint")
    parser.add_argument("action", choices=("enable", "disable", "status"))
    args = parser.parse_args()

    gate = VideoGate(VideoConfig.from_env().enable_file)
    if args.action == "enable":
        gate.enable()
    elif args.action == "disable":
        gate.disable()

    print("enabled" if gate.enabled() else "disabled")


if __name__ == "__main__":
    main()
