import rosie
from rosie.__main__ import main


def test_version_is_set():
    assert rosie.__version__


def test_main_prints_greeting(capsys):
    assert main([]) == 0
    assert "Rosie" in capsys.readouterr().out


def test_package_and_pyproject_versions_match():
    import tomllib
    from pathlib import Path

    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    assert data["project"]["version"] == rosie.__version__
