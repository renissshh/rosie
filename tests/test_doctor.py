import httpx

from rosie.__main__ import main
from rosie.config import LLMConfig, RosieConfig
from rosie.doctor import (
    Check,
    check_api_key,
    check_data_dir,
    check_llm,
    check_permissions,
    check_python,
    check_user_vault,
    report,
    run_checks,
)


def ollama(models=("qwen3:8b",), status=200):
    def handler(request):
        assert request.url.path == "/v1/models"
        return httpx.Response(status, json={"data": [{"id": m} for m in models]})

    return httpx.Client(transport=httpx.MockTransport(handler))


def down():
    def handler(request):
        raise httpx.ConnectError("refused")

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_python_version():
    assert check_python((3, 12)).status == "ok"
    assert check_python((3, 10)).status == "fail"


def test_data_dir_is_created_and_left_clean(tmp_path):
    config = RosieConfig(data_dir=tmp_path / "Rosie")
    assert check_data_dir(config).status == "ok"
    assert list((tmp_path / "Rosie").iterdir()) == []


def test_data_dir_unwritable(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    assert check_data_dir(RosieConfig(data_dir=blocker / "Rosie")).status == "fail"


def test_llm_ok_missing_model_and_down():
    llm = LLMConfig()
    assert check_llm(llm, ollama()).status == "ok"
    missing = check_llm(llm, ollama(models=("llama3.2:3b",)))
    assert missing.status == "fail" and "ollama pull qwen3:8b" in missing.detail
    dead = check_llm(llm, down())
    assert dead.status == "fail" and "ollama serve" in dead.detail
    assert check_llm(llm, ollama(status=500)).status == "fail"


def test_api_key_never_printed():
    llm = LLMConfig(provider="openai_compatible", api_key_env="GEMINI_API_KEY")
    ok = check_api_key(llm, {"GEMINI_API_KEY": "AIza-super-secret"})
    assert ok.status == "ok" and "super-secret" not in ok.line()
    assert check_api_key(llm, {}).status == "warn"


def test_user_vault(tmp_path):
    assert check_user_vault(RosieConfig(data_dir=tmp_path / "d")).status == "warn"
    gone = RosieConfig(data_dir=tmp_path / "d", user_vault_dir=tmp_path / "gone")
    assert check_user_vault(gone).status == "fail"
    (tmp_path / "v").mkdir()
    there = RosieConfig(data_dir=tmp_path / "d", user_vault_dir=tmp_path / "v")
    assert check_user_vault(there).status == "ok"


def test_permissions(tmp_path):
    assert check_permissions().status == "ok"
    assert check_permissions(tmp_path / "missing.yaml").status == "warn"


def test_report_exit_code():
    text, code = report([Check("A", "ok", "fine"), Check("B", "warn", "meh")])
    assert code == 0 and text.endswith("All good. Run `rosie chat`.")
    assert text.splitlines()[0] == "[ok]   A: fine"
    text, code = report([Check("A", "fail", "broken")])
    assert code == 1 and "1 check(s) failed" in text


def test_run_checks_with_fallback(tmp_path):
    config = RosieConfig(
        data_dir=tmp_path,
        fallback_llm=LLMConfig(provider="openai_compatible", api_key_env="K", model="gemini"),
    )
    names = [c.name for c in run_checks(config, ollama(), {})]
    assert names == [
        "Python",
        "Data folder",
        "LLM",
        "Fallback key",
        "Fallback LLM",
        "Your vault",
        "Permissions",
    ]


def test_cli_doctor_fails_when_ollama_is_down(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ROSIE_DATA_DIR", str(tmp_path / "Rosie"))
    monkeypatch.setenv("ROSIE_LLM_BASE_URL", "http://127.0.0.1:9/v1")
    assert main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "[fail] LLM" in out and "[ok]   Data folder" in out
