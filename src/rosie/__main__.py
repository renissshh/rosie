"""Entry point: `python -m rosie` or the `rosie` command.

    rosie chat [--config PATH]    talk to Rosie in the terminal
    rosie doctor [--config PATH]  check the setup (Python, D:\\Rosie, Ollama, vault)
    rosie vault [--config PATH]   create rosie-vault's folders and sync it with git
    rosie telegram [--config PATH] answer on Telegram (needs TELEGRAM_* in .env)
    rosie brief [--config PATH]   print today's morning brief
    rosie review [--config PATH]  nightly review: three questions in the terminal
    rosie stt-bench FOLDER [--model base.en]  speech-to-text speed/accuracy on recordings
    rosie voices                  list Rosie's voices
    rosie voice [--config PATH]   hands-free: "Hey Rosie", then talk (needs [voice])
    rosie say TEXT [--voice NAME] [--out FILE.wav]  hear (or save) a voice
    rosie serve [--voice]         Rosie's core for the orb UI (WebSocket on 127.0.0.1:8765)
    rosie server [--config PATH]  always-on mode: Telegram + reminders + vault git sync
    rosie --version

Config file lookup: --config, then the ROSIE_CONFIG env var, then
./config/rosie.yaml. Secrets come from `.env` in the current folder, then from the
repo folder above config/ (so the core finds them when the orb starts it at login).
"""

from __future__ import annotations

import argparse
import os
import threading
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from pathlib import Path

from rosie import __version__
from rosie.backup import schedule_backups
from rosie.brief import BRIEF_JOB, MorningBrief, build_brief, coach_notes
from rosie.builtin_tools import register_builtin_tools
from rosie.config import RosieConfig, load_config, load_dotenv
from rosie.context import ContextBuilder
from rosie.llm import LLMError
from rosie.memory import FactStore, register_memory_tools
from rosie.notify import DesktopNotifier, Router
from rosie.prompt import now_in
from rosie.quiz import register_quiz_tool
from rosie.ratelimit import RateLimiter
from rosie.reminders import Reminders, register_reminder_tools
from rosie.review import REVIEW_JOB, NightlyReview, run_in_terminal
from rosie.scheduler import Scheduler
from rosie.search import NoteIndex, register_search_tool
from rosie.study import StudyTimer, register_study_tools
from rosie.tasks import TaskStore, register_task_tools
from rosie.tools import ToolRegistry
from rosie.training import TrainingLog, register_training_tools
from rosie.vault_writer import VaultWriter

TELEGRAM_PER_MINUTE = 20


def find_config(arg: str | None, environ: Mapping[str, str] | None = None) -> Path | None:
    environ = os.environ if environ is None else environ
    if arg:
        return Path(arg)
    if environ.get("ROSIE_CONFIG"):
        return Path(environ["ROSIE_CONFIG"])
    default = Path("config") / "rosie.yaml"
    return default if default.is_file() else None


def load_env(config_arg: str | None) -> Path | None:
    """Find rosie.yaml and load secrets from `.env`: the current folder first, then the
    folder above `config/` (the repo). The second matters when the orb starts the core at
    login, from a folder that isn't the repo. Variables already set always win."""
    config_path = find_config(config_arg)
    load_dotenv(Path(".env"))
    if config_path is not None:
        load_dotenv(config_path.resolve().parent.parent / ".env")
    return config_path


def build_registry(config: RosieConfig, reminders: Reminders | None = None) -> ToolRegistry:
    """All tools Rosie has today. Reminder tools need a running scheduler, so they're optional."""
    registry = ToolRegistry()
    register_builtin_tools(registry, config)
    register_memory_tools(registry, fact_store(config))
    register_task_tools(registry, task_store(config))
    register_search_tool(registry, note_index(config))
    register_study_tools(registry, study_timer(config), config.subjects, lambda: today_in(config))
    register_quiz_tool(registry, config)
    register_training_tools(
        registry, TrainingLog(vault_writer(config), lambda: now_in(config.timezone))
    )
    if reminders is not None:
        register_reminder_tools(registry, reminders)
    return registry


def desktop_or_none() -> DesktopNotifier | None:
    """Windows toasts when on Windows; elsewhere notifications skip the desktop."""
    desktop = DesktopNotifier()
    return desktop if desktop.available else None


def start_reminders(
    config: RosieConfig, notify, on_review: Callable[[], None] | None = None
) -> tuple[Reminders, threading.Event]:
    """Scheduler thread with reminders, morning brief and nightly review. Set the event to stop.

    `on_review` starts the review where it can be answered (Telegram); without it Rosie
    just reminds you to run `rosie review`.
    """
    reminders = build_schedule(config, notify, on_review)
    stop = threading.Event()
    threading.Thread(target=reminders.scheduler.run_forever, args=(stop,), daemon=True).start()
    return reminders, stop


def build_schedule(
    config: RosieConfig,
    notify,
    on_review: Callable[[], None] | None = None,
    now: Callable[[], datetime] | None = None,
) -> Reminders:
    """Everything Rosie does on a clock, wired but not started: reminders, morning brief,
    nightly review and vault backups. `now` (UTC) lets tests run a whole day in a second
    (tests/test_whole_day.py); safe to call on every start, nothing gets scheduled twice."""
    db = config.data_dir / "index" / "scheduler.db"
    scheduler = Scheduler(db, config.timezone, now) if now else Scheduler(db, config.timezone)
    reminders = Reminders(scheduler, notify, vault_writer(config), config.timezone)
    if config.clock == "server":
        # An always-on server sends the brief and review; this machine only keeps its
        # own reminders, so nothing arrives twice.
        scheduler.drop(BRIEF_JOB)
        scheduler.drop(REVIEW_JOB)
    else:
        coach = lambda: coach_notes(config.vault_dir, config.subjects, today_in(config))  # noqa: E731
        MorningBrief(task_store(config), vault_writer(config), notify, reminders, coach).schedule(
            config.brief_time
        )
        scheduler.on(
            REVIEW_JOB,
            lambda job: (
                on_review()
                if on_review
                else notify("Rosie", "Time for your nightly review: run `rosie review`.")
            ),
        )
        scheduler.ensure_daily(REVIEW_JOB, config.review_time)
    schedule_backups(
        scheduler, config.vault_dir, config.data_dir / "backups", lambda: today_in(config)
    )
    return reminders


def note_index(config: RosieConfig) -> NoteIndex:
    vaults = {"rosie": config.vault_dir}
    if config.user_vault_dir is not None:
        vaults["yours"] = config.user_vault_dir
    return NoteIndex(config.data_dir / "index" / "notes.db", vaults)


def vault_writer(config: RosieConfig) -> VaultWriter:
    forbidden = [config.user_vault_dir] if config.user_vault_dir else []
    return VaultWriter(config.vault_dir, forbidden=forbidden)


def study_timer(config: RosieConfig) -> StudyTimer:
    state = config.data_dir / "index" / "study_session.json"
    return StudyTimer(state, vault_writer(config), lambda: now_in(config.timezone))


def task_store(config: RosieConfig) -> TaskStore:
    return TaskStore(vault_writer(config), today=lambda: today_in(config))


def today_in(config: RosieConfig) -> date:
    return now_in(config.timezone).date()


def fact_store(config: RosieConfig) -> FactStore:
    return FactStore(vault_writer(config), config.data_dir / "index" / "memory.db")


def telegram_reply(text: str, review: NightlyReview, session, limiter=None) -> str:
    """While the nightly review is running, messages are its answers; otherwise chat.
    More than 20 messages a minute get a "slow down" instead of reaching the agent."""
    if limiter is not None and not limiter.allow():
        return f"Slow down a little: try again in {limiter.retry_after():.0f} s."
    if review.active:
        return review.answer(text)
    if text.strip().lower() in {"/review", "review"}:
        return review.start()
    try:
        return session.ask(text).text
    except LLMError:
        return "I can't reach my brain right now (is Ollama running on the laptop?)."


def add_voice_notes(bot, config: RosieConfig) -> bool:
    """Voice notes in and out on Telegram, if the [voice] extras are installed."""
    from rosie.stt import WhisperTranscriber
    from rosie.tts import Speaker, TTSError
    from rosie.voice_notes import decode_to_pcm, encode_ogg_opus

    models = config.data_dir / "models"
    try:
        stt = WhisperTranscriber("base.en", models)
        speaker = Speaker(config.voice, models)
    except (RuntimeError, TTSError) as exc:
        print(f"Voice notes off: {exc}")
        return False
    bot.hear = lambda data: stt.transcribe(decode_to_pcm(data)).text
    bot.speak = lambda text: encode_ogg_opus(*speaker.synthesize(text))
    return True


def start_vault_sync(config: RosieConfig, stop: threading.Event) -> threading.Thread:
    """Keep rosie-vault in step with its git remote in the background."""
    from rosie.vault import GitSync, ensure_layout, sync_forever

    ensure_layout(config.vault_dir)
    thread = threading.Thread(
        target=sync_forever,
        args=(GitSync(config.vault_dir), stop, config.vault_sync_minutes * 60),
        daemon=True,
    )
    thread.start()
    return thread


def run_telegram(
    config_arg: str | None,
    environ: Mapping[str, str] | None = None,
    server: bool = False,
) -> int:
    """`rosie telegram`; with server=True it is `rosie server`: the same bot, plus the
    vault kept in sync with git, for an always-on machine (see docs/SERVER.md)."""
    from rosie.chat import build_session
    from rosie.telegram import TelegramError, bot_from_env

    config = load_config(load_env(config_arg))
    try:
        bot = bot_from_env(os.environ if environ is None else environ)
    except TelegramError as exc:
        print(f"Telegram is not set up: {exc}")
        return 1
    review = NightlyReview(task_store(config), vault_writer(config))
    reminders, stop = start_reminders(
        config, Router(desktop_or_none(), bot.notify), on_review=lambda: bot.send(review.start())
    )
    context = ContextBuilder(fact_store(config), task_store(config))
    session = build_session(
        config, build_registry(config, reminders), context=context.build, ask_user=bot.ask
    )
    limiter = RateLimiter(TELEGRAM_PER_MINUTE)
    bot.on_message = lambda text: telegram_reply(text, review, session, limiter)
    add_voice_notes(bot, config)
    sync = start_vault_sync(config, stop) if server else None
    print(("Rosie server" if server else "Rosie") + " is listening on Telegram. Ctrl+C to stop.")
    try:
        bot.run_forever(stop)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        if sync is not None:
            sync.join(timeout=60)  # last push before exit
    return 0


def build_voice_loop(config: RosieConfig, think, on_state, on_transcript=None):
    """Microphone, wake word, speech-to-text and voice, wired into a VoiceLoop.

    Returns (loop, microphone). Raises RuntimeError/TTSError/ImportError when the
    [voice] extras or models are missing.
    """
    from rosie.audio import Microphone
    from rosie.stt import WhisperTranscriber
    from rosie.tts import Speaker
    from rosie.voice_loop import SoundDevicePlayer, VoiceLoop
    from rosie.wakeword import OpenWakeWord, SpokenName

    models = config.data_dir / "models"
    mic, player = Microphone(), SoundDevicePlayer()
    stt = WhisperTranscriber("base.en", models)
    speaker = Speaker(config.voice, models)
    trained = models / "hey_rosie.onnx"
    wake = OpenWakeWord(str(trained)) if trained.is_file() else SpokenName(stt)
    loop = VoiceLoop(
        wake,
        stt,
        think,
        speaker.synthesize,
        player,
        on_state=on_state,
        on_transcript=on_transcript or (lambda role, text: None),
    )
    return loop, mic


def run_voice(config_arg: str | None) -> int:
    """Wire microphone, wake word, speech-to-text, the agent and the voice together."""
    from rosie.chat import build_session
    from rosie.tts import TTSError

    config = load_config(load_env(config_arg))
    terminal = lambda title, text: print(f"[{title}] {text}")  # noqa: E731
    holder: dict = {}
    try:
        loop, mic = build_voice_loop(
            config,
            lambda text: holder["session"].ask(text).text,
            on_state=lambda state: print(f"[{state}]"),
        )
    except (RuntimeError, TTSError, ImportError) as exc:
        print(exc)
        return 1
    reminders, stop = start_reminders(config, Router(desktop_or_none(), terminal))
    context = ContextBuilder(fact_store(config), task_store(config))
    holder["session"] = build_session(
        config, build_registry(config, reminders), context=context.build
    )
    print('Say "Hey Rosie". Ctrl+C to stop.')
    try:
        loop.run(mic.frames())
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
    return 0


def start_orb_voice(config: RosieConfig, bridge, think, build=None):
    """`rosie serve --voice`: the hands-free loop in a thread, its states shown on the orb.

    Returns the VoiceLoop, or None (with the reason printed) if voice can't start;
    the orb then works by typing only.
    """
    from rosie.tts import TTSError

    build = build or build_voice_loop
    try:
        loop, mic = build(
            config,
            think,
            on_state=lambda state: bridge.emit({"type": "state", "state": state}, keep=True),
            on_transcript=lambda role, text: bridge.emit(
                {"type": "transcript", "role": role, "text": text}
            ),
        )
    except (RuntimeError, TTSError, ImportError) as exc:
        print(f"Voice off: {exc}")
        return None
    threading.Thread(target=loop.run, args=(mic.frames(),), daemon=True).start()

    def listen(message):
        loop.wake_now()
        return None

    bridge.on("listen", listen)
    return loop


def run_serve(
    config_arg: str | None,
    port: int,
    stop: threading.Event | None = None,
    voice: bool = False,
) -> int:
    """The core the orb talks to: agent, reminders and brief behind one local WebSocket."""
    from rosie.bridge import Bridge, BridgeError, ChatHandlers, orb_notifier
    from rosie.chat import build_session
    from rosie.day import DayWatcher, watch_forever
    from rosie.doctor import run_checks
    from rosie.health import HealthFeed
    from rosie.quicklog import DeckFeed, QuickLog

    config = load_config(load_env(config_arg))
    bridge = Bridge(port=port)
    stop = stop or threading.Event()
    reminders, scheduler_stop = start_reminders(
        config, orb_notifier(bridge, desktop_or_none()), on_review=None
    )
    context = ContextBuilder(fact_store(config), task_store(config))
    session = build_session(
        config, build_registry(config, reminders), context=context.build, ask_user=bridge.ask_user
    )

    lock = threading.Lock()  # typed and spoken messages share one conversation

    def ask(text: str) -> str:
        with lock:
            try:
                return session.ask(text).text
            except LLMError:
                return "I can't reach my brain right now. Is Ollama running? Try `ollama serve`."

    now = lambda: now_in(config.timezone)  # noqa: E731
    tasks = task_store(config)
    deck = DeckFeed(bridge, QuickLog(vault_writer(config), tasks, now), config.countdowns)
    ChatHandlers(bridge, ask, after=deck.refresh)
    watcher = DayWatcher(config.day_blocks, reminders.scheduler.jobs, bridge.emit)
    health = HealthFeed(bridge, lambda: run_checks(config))
    threading.Thread(
        target=watch_forever,
        args=([health.tick, watcher.tick, deck.refresh], now, scheduler_stop),
        daemon=True,
    ).start()
    start_vault_sync(config, scheduler_stop)
    if not (voice and start_orb_voice(config, bridge, ask)):

        def no_voice(message):
            raise BridgeError("voice is off: start the core with `rosie serve --voice`")

        bridge.on("listen", no_voice)
    bridge.emit({"type": "state", "state": "idle"}, keep=True)
    print(f"Rosie's core is up on ws://127.0.0.1:{port}. Ctrl+C to stop.")
    try:
        bridge.run_forever(stop)
    except KeyboardInterrupt:
        pass
    except OSError as exc:  # usually: the port is taken by a core that's already running
        print(f"Can't listen on 127.0.0.1:{port} ({exc.strerror or exc}).")
        print("Is Rosie's core already running? The orb connects to that one.")
        return 1
    finally:
        scheduler_stop.set()
    return 0


def run_say(text: str, voice: str | None, out: str | None, config_arg: str | None) -> int:
    from rosie.audio import play, write_wav
    from rosie.tts import Speaker, TTSError

    config = load_config(find_config(config_arg))
    try:
        speaker = Speaker(voice or config.voice, config.data_dir / "models")
        pcm, rate = speaker.synthesize(text)
        if out:
            print(f"saved {write_wav(Path(out), pcm, rate)}")
        else:
            play(pcm, rate)
    except (TTSError, RuntimeError) as exc:
        print(exc)
        return 1
    return 0


def run_stt_bench(folder: Path, model: str, config_arg: str | None = None) -> int:
    from rosie.stt import WhisperTranscriber, benchmark, load_samples, report

    config = load_config(find_config(config_arg))
    try:
        transcriber = WhisperTranscriber(model, config.data_dir / "models")
    except RuntimeError as exc:
        print(exc)
        return 1
    text = report(benchmark(transcriber, load_samples(folder)), model)
    out = config.logs_dir / "stt-bench.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text + f"\nSaved to {out}")
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
    bench = sub.add_parser("stt-bench", help="benchmark speech-to-text on name.wav + name.txt")
    bench.add_argument("folder")
    bench.add_argument("--model", default="base.en")
    bench.add_argument("--config", help="path to rosie.yaml")
    sub.add_parser("voices", help="list Rosie's voices")
    voice = sub.add_parser("voice", help='hands-free mode: say "Hey Rosie"')
    voice.add_argument("--config", help="path to rosie.yaml")
    say = sub.add_parser("say", help="speak a sentence with one of the voices")
    say.add_argument("text")
    say.add_argument("--voice", help="voice name (default: `voice` in rosie.yaml)")
    say.add_argument("--out", help="save to a WAV file instead of playing")
    say.add_argument("--config", help="path to rosie.yaml")
    serve = sub.add_parser("serve", help="run Rosie's core for the orb UI")
    serve.add_argument("--config", help="path to rosie.yaml")
    serve.add_argument("--port", type=int, default=8765, help="WebSocket port (default 8765)")
    serve.add_argument("--voice", action="store_true", help='also listen for "Hey Rosie"')
    server = sub.add_parser("server", help="always-on mode (Docker): Telegram + vault sync")
    server.add_argument("--config", help="path to rosie.yaml")
    review = sub.add_parser("review", help="nightly review in the terminal")
    review.add_argument("--config", help="path to rosie.yaml")
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

        config = load_config(load_env(args.config))
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

        text, code = report(run_checks(load_config(load_env(args.config))))
        print(text)
        return code
    if args.command == "brief":
        config = load_config(find_config(args.config))
        coach = lambda: coach_notes(config.vault_dir, config.subjects, today_in(config))  # noqa: E731
        print(build_brief(task_store(config), coach=coach), end="")
        return 0
    if args.command == "voices":
        from rosie.tts import VOICES

        config = load_config(find_config(None))
        for voice in VOICES.values():
            mark = "*" if voice.name == config.voice else " "
            print(f"{mark} {voice.name:16} {voice.description}")
        return 0
    if args.command == "voice":
        return run_voice(args.config)
    if args.command == "say":
        return run_say(args.text, args.voice, args.out, args.config)
    if args.command == "stt-bench":
        return run_stt_bench(Path(args.folder), args.model, args.config)
    if args.command == "review":
        config = load_config(find_config(args.config))
        run_in_terminal(NightlyReview(task_store(config), vault_writer(config)), input, print)
        return 0
    if args.command == "telegram":
        return run_telegram(args.config)
    if args.command == "server":
        return run_telegram(args.config, server=True)
    if args.command == "serve":
        return run_serve(args.config, args.port, voice=args.voice)
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
