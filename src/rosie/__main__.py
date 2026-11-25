"""Entry point: `python -m rosie` or the `rosie` command.

    rosie chat [--config PATH]    talk to Rosie in the terminal
    rosie --version

Config file lookup: --config, then the ROSIE_CONFIG env var, then
./config/rosie.yaml. A `.env` in the current folder is loaded for secrets.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from rosie import __version__
from rosie.config import load_config, load_dotenv
from rosie.tools import ToolRegistry


def find_config(arg: str | None, environ: Mapping[str, str] | None = None) -> Path | None:
    environ = os.environ if environ is None else environ
    if arg:
        return Path(arg)
    if environ.get("ROSIE_CONFIG"):
        return Path(environ["ROSIE_CONFIG"])
    default = Path("config") / "rosie.yaml"
    return default if default.is_file() else None


def build_registry() -> ToolRegistry:
    """All tools Rosie has today."""
    return ToolRegistry()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rosie", description="Rosie, your chief of staff.")
    parser.add_argument("--version", action="version", version=f"Rosie {__version__}")
    sub = parser.add_subparsers(dest="command")
    chat = sub.add_parser("chat", help="talk to Rosie in the terminal")
    chat.add_argument("--config", help="path to rosie.yaml")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command is None:
        print(f"Rosie {__version__} is awake. Run `rosie chat` to talk.")
        return 0
    if args.command == "chat":
        from rosie.chat import build_session, run_chat

        load_dotenv(Path(".env"))
        config = load_config(find_config(args.config))
        run_chat(build_session(config, build_registry()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
