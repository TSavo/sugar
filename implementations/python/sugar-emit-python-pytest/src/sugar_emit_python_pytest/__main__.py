from __future__ import annotations

import argparse

from .rpc import run_rpc


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="sugar-emit-python-pytest",
        description="PEP 1.7.0 pytest emitter kit (predicate -> pytest assertion).",
    )
    parser.add_argument(
        "--rpc", action="store_true", help="run PEP 1.7.0 JSON-RPC over stdio"
    )
    args = parser.parse_args(argv)
    if args.rpc:
        run_rpc()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
