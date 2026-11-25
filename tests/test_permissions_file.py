"""Guards the user's permission decisions (docs/decisions/0001) against accidental edits."""

from pathlib import Path

import yaml

POLICY = yaml.safe_load(
    (Path(__file__).parents[1] / "config" / "permissions.yaml").read_text(encoding="utf-8")
)
ACTIONS = POLICY["actions"]


def test_every_value_is_a_known_decision():
    assert set(ACTIONS.values()) <= {"allow", "ask", "deny"}


def test_users_own_vault_is_never_writable():
    assert ACTIONS["vault.user.read"] == "allow"
    assert ACTIONS["vault.user.write"] == "deny"
    assert ACTIONS["vault.user.delete"] == "deny"


def test_outside_world_actions_need_a_yes():
    for action in ("calendar.write", "email.send", "message.others", "pc.run_script"):
        assert ACTIONS[action] == "ask", action


def test_payments_denied():
    assert ACTIONS["payments"] == "deny"


def test_proactive_contact_is_limited():
    assert set(POLICY["proactive"]["allowed"]) == {
        "morning_brief",
        "nightly_review",
        "due_reminder",
    }
    assert "study" in POLICY["proactive"]["quiet_during"]
