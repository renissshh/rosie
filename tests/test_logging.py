import logging

from rosie.logging_setup import mask_secrets, setup_logging

TELEGRAM = "123456789:" + "A" * 35
GOOGLE = "AIza" + "B" * 35


def test_masks_telegram_token():
    assert TELEGRAM not in mask_secrets(f"token={TELEGRAM}")


def test_masks_google_key():
    assert mask_secrets(f"key {GOOGLE} end") == "key *** end"


def test_masks_bearer_keeps_prefix():
    assert mask_secrets("Authorization: Bearer abcdefghijklmnop1234") == (
        "Authorization: Bearer ***"
    )


def test_plain_text_untouched():
    assert mask_secrets("study DBMS at 6") == "study DBMS at 6"


def test_file_log_is_masked(tmp_path):
    logger = setup_logging(tmp_path / "logs", level=logging.DEBUG)
    logger.info("got %s", TELEGRAM)
    for h in logger.handlers:
        h.flush()
    content = (tmp_path / "logs" / "rosie.log").read_text(encoding="utf-8")
    assert "got ***" in content
    assert TELEGRAM not in content


def test_console_can_be_quieter_than_file(tmp_path):
    logger = setup_logging(tmp_path, console_level=logging.WARNING)
    console, file_handler = logger.handlers
    assert console.level == logging.WARNING
    assert file_handler.level == logging.NOTSET  # file keeps everything at INFO and up
    logger.handlers.clear()
