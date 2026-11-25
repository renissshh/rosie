import rosie
from rosie.__main__ import main


def test_version_is_set():
    assert rosie.__version__


def test_main_prints_greeting(capsys):
    assert main([]) == 0
    assert "Rosie" in capsys.readouterr().out
