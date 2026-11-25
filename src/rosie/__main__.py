"""Entry point: `python -m rosie` or the `rosie` command.

    rosie chat [--config PATH]    talk to Rosie in the terminal
    rosie doctor [--config PATH]  check the setup (Python, D:\\Rosie, Ollama, vault)
    rosie vault [--config PATH]   create rosie-vault's folders and sync it with git
    rosie telegram [--config PATH] answer on Telegram (needs TELEGRAM_* in .env)
    rosie brief [--config PATH]   print today's morning brief
    rosie --version

Config file lookup: --config, then the ROSIE_CONFIG env var, then
./config/rosie.yaml. A `.env` in the current folder is loaded for secrets.
"""

from __future__ import annotations

import argparse
import os
import threading
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

from rosie import __version__
from rosie.brief import MorningBrief, build_brief
from rosie.builtin_tools import register_builtin_tools
from rosie.config import RosieConfig, load_config, load_dotenv
from rosie.context import ContextBuilder
from rosie.memory import FactStore, register_memory_tools
from rosie.notify import DesktopNotifier, Router
from rosie.prompt import now_in
from rosie.reminders import Reminders, register_reminder_tools
from rosie.scheduler import Scheduler
from rosie.search import NoteIndex, register_search_tool
from rosie.tasks import TaskStore, register_task_tools
from rosie.tools import ToolRegistry
from rosie.vault_writer import VaultWriter


def find_config(arg: str | None, environ: Mapping[str, str] | None = None) -> Path | None:
    environ = os.environ if environ is None else environ
    if arg:
        return Path(arg)
    if environ.get("ROSIE_CONFIG"):
        return Path(environ["ROSIE_CONFIG"])
    default = Path("config") / "rosie.yaml"
    return default if default.is_file() else None


def build_registry(config: RosieConfig, reminders: Reminders | None = None) -> ToolRegistry:
    """All tools Rosie has today. Reminder tools need a running scheduler, so they're optional."""
    registry = ToolRegistry()
    register_builtin_tools(registry, config)
    register_memory_tools(registry, fact_store(config))
    register_task_tools(registry, task_store(config))
    register_search_tool(registry, note_index(config))
    if reminders is not None:
        register_reminder_tools(registry, reminders)
    return registry


def desktop_or_none() -> DesktopNotifier | None:
    """Windows toasts when on Windows; elsewhere notifications skip the desktop."""
    desktop = DesktopNotifier()
    return desktop if desktop.available else None


def start_reminders(config: RosieConfig, notify) -> tuple[Reminders, threading.Event]:
    """Scheduler thread for the chat session. Set the returned event to stop it."""
    scheduler = Scheduler(config.data_dir / "index" / "scheduler.db", config.timezone)
    reminders = Reminders(scheduler, notify, vault_writer(config), config.timezone)
    MorningBrief(task_store(config), vault_writer(config), notify, reminders).schedule(
        config.brief_time
    )
    stop = threading.Event()
    threading.Thread(target=scheduler.run_forever, args=(stop,), daemon=True).start()
    return reminders, stop


def note_index(config: RosieConfig) -> NoteIndex:
    vaults = {"rosie": config.vault_dir}
    if config.user_vault_dir is not None:
        vaults["yours"] = config.user_vault_dir
    return NoteIndex(config.data_dir / "index" / "notes.db", vaults)


def vault_writer(config: RosieConfig) -> VaultWriter:
    forbidden = [config.user_vault_dir] if config.user_vault_dir else []
    return VaultWriter(config.vault_dir, forbidden=forbidden)


def task_store(config: RosieConfig) -> TaskStore:
    return TaskStore(vault_writer(config), today=lambda: today_in(config))


def today_in(config: RosieConfig) -> date:
    return now_in(config.timezone).date()


def fact_store(config: RosieConfig) -> FactStore:
    return FactStore(vault_writer(config), config.data_dir / "index" / "memory.db")


def run_telegram(config_arg: str | None, environ: Mapping[str, str] | None = None) -> int:
    from rosie.chat import build_session
    from rosie.telegram import TelegramError, bot_from_env

    load_dotenv(Path(".env"))
    config = load_config(find_config(config_arg))
    try:
        bot = bot_from_env(os.environ if environ is None else environ)
    except TelegramError as exc:
        print(f"Telegram is not set up: {exc}")
        return 1
    reminders, stop = start_reminders(config, Router(desktop_or_none(), bot.notify))
    context = ContextBuilder(fact_store(config), task_store(config))
    session = build_session(
        config, build_registry(config, reminders), context=context.build, ask_user=bot.ask
    )
    bot.on_message = lambda text: session.ask(text).text
    print("Rosie is listening on Telegram. Ctrl+C to stop.")
    try:
        bot.run_forever(stop)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rosie", description="Rosie, your chief of staff.")
    parser.add_argument("--version", action="version", version=f"Rosie {__version__}")
    sub = parser.add_subparsers(dest="command")
    chat = sub.add_parser("chat", help="talk to Rosie in the terminal")
    chat.add_argument("--config", help="path to rosie.yaml")
    doctor = sub.add_parser("doctor", help="check that Rosie is set up correctly")
    doctor.add_argument("--config", help="path to rosie.yaml")
    vault = sub.add_parser("vault", help="set up and sync rosie-vault")
    vault.add_argument("--config", help="path to rosie.yaml")
    brief = sub.add_parser("brief", help="print today's morning brief")
    brief.add_argument("--config", help="path to rosie.yaml")
    telegram = sub.add_parser("telegram", help="answer on Telegram from your phone")
    telegram.add_argument("--config", help="path to rosie.yaml")
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
        context = ContextBuilder(fact_store(config), task_store(config))
        terminal = lambda title, text: print(f"\n[{title}] {text}")  # noqa: E731
        reminders, stop = start_reminders(config, Router(desktop_or_none(), terminal))
        registry = build_registry(config, reminders)
        try:
            run_chat(build_session(config, registry, context=context.build))
        finally:
            stop.set()
    if args.command == "doctor":
        from rosie.doctor import report, run_checks

        load_dotenv(Path(".env"))
        text, code = report(run_checks(load_config(find_config(args.config))))
        print(text)
        return code
    if args.command == "brief":
        print(build_brief(task_store(load_config(find_config(args.config)))), end="")
        return 0
    if args.command == "telegram":
        return run_telegram(args.config)
    if args.command == "vault":
        from rosie.vault import GitSync, ensure_layout

        config = load_config(find_config(args.config))
        created = ensure_layout(config.vault_dir)
        result = GitSync(config.vault_dir).sync("rosie: sync vault")
        print(f"rosie-vault: {config.vault_dir} ({len(created)} new files)")
        print("synced" if result.pushed else result.error or "committed locally (no remote)")
        return 0 if result.ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
