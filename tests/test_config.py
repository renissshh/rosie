from pathlib import Path

import pytest

from rosie.config import (
    WINDOWS_DATA_DIR,
    default_data_dir,
    load_config,
    load_dotenv,
    parse_dotenv,
)


def test_windows_defaults_to_d_drive():
    assert default_data_dir("win32") == WINDOWS_DATA_DIR == Path("D:/Rosie")


def test_non_windows_defaults_to_home():
    assert default_data_dir("linux") == Path.home() / ".rosie"


def test_vault_dir_derived_from_data_dir(tmp_path):
    cfg = load_config(environ={"ROSIE_DATA_DIR": str(tmp_path)})
    assert cfg.vault_dir == tmp_path / "rosie-vault"
    assert cfg.logs_dir == tmp_path / "logs"


def test_yaml_overrides_defaults(tmp_path):
    f = tmp_path / "rosie.yaml"
    f.write_text("timezone: UTC\nllm:\n  model: llama3.2\n", encoding="utf-8")
    cfg = load_config(f, environ={})
    assert cfg.timezone == "UTC"
    assert cfg.llm.model == "llama3.2"
    assert cfg.llm.provider == "ollama"


def test_env_overrides_yaml(tmp_path):
    f = tmp_path / "rosie.yaml"
    f.write_text("llm:\n  model: from-yaml\n", encoding="utf-8")
    cfg = load_config(f, environ={"ROSIE_LLM_MODEL": "from-env"})
    assert cfg.llm.model == "from-env"


def test_missing_yaml_is_fine(tmp_path):
    cfg = load_config(tmp_path / "nope.yaml", environ={})
    assert cfg.max_agent_steps == 8


def test_non_mapping_yaml_rejected(tmp_path):
    f = tmp_path / "rosie.yaml"
    f.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(f, environ={})


@pytest.mark.parametrize(
    "rosie_vault, user_vault",
    [("v", "v"), ("v/inner", "v"), ("v", "v/inner")],
)
def test_rosie_vault_must_not_overlap_user_vault(tmp_path, rosie_vault, user_vault):
    env = {
        "ROSIE_VAULT_DIR": str(tmp_path / rosie_vault),
        "ROSIE_USER_VAULT_DIR": str(tmp_path / user_vault),
    }
    with pytest.raises(ValueError, match="separate"):
        load_config(environ=env)


def test_separate_vaults_accepted(tmp_path):
    env = {
        "ROSIE_VAULT_DIR": str(tmp_path / "rosie-vault"),
        "ROSIE_USER_VAULT_DIR": str(tmp_path / "my-notes"),
    }
    cfg = load_config(environ=env)
    assert cfg.user_vault_dir == tmp_path / "my-notes"


def test_parse_dotenv_handles_comments_quotes_export():
    text = "# c\nA=1\nexport B=\"two\"\nC='three'\n\nbad line\n"
    assert parse_dotenv(text) == {"A": "1", "B": "two", "C": "three"}


def test_load_dotenv_does_not_override(tmp_path):
    f = tmp_path / ".env"
    f.write_text("KEY=from-file\nNEW=x\n", encoding="utf-8")
    env = {"KEY": "already"}
    load_dotenv(f, env)
    assert env == {"KEY": "already", "NEW": "x"}
