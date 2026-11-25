"""Entry point: `python -m rosie` or the `rosie` command."""

from rosie import __version__


def main() -> None:
    print(f"Rosie {__version__} is awake. The agent loop arrives in Sprint 1.")


if __name__ == "__main__":
    main()
