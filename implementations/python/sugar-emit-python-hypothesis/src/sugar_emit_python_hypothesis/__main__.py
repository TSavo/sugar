"""Command entry point for the Hypothesis emitter plugin."""

from __future__ import annotations

import argparse

from .rpc import run_rpc


def main() -> None:
    parser = argparse.ArgumentParser(prog="sugar-emit-python-hypothesis")
    parser.add_argument(
        "--rpc", action="store_true", help="serve newline-delimited JSON-RPC"
    )
    args = parser.parse_args()
    if args.rpc:
        run_rpc()
        return
    parser.error("only --rpc is supported")


if __name__ == "__main__":
    main()
