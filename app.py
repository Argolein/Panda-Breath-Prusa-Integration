#!/usr/bin/env python3

from __future__ import annotations

import argparse
import logging
import sys

from panda_prusa_bridge.config import BridgeConfig
from panda_prusa_bridge.server import run_server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Panda Breath bridge for Prusa Core One via PrusaLink."
    )
    parser.add_argument(
        "--config",
        default="config.json",
        help="Path to the JSON configuration file.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = BridgeConfig.load(args.config)

    logging.basicConfig(
        level=config.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    run_server(config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
