import pytest

from rosie.agent import Agent
from rosie.llm import ChatResult, ToolCall
from rosie.safety import DEFAULT_POLICY_PATH, PermissionPolicy, SafetyGate, describe_call
from rosie.tools import Tool, ToolRegistry


def tool(name="t", tier="read", action=None, description="Do a thing"):
    return Tool(name, description, lambda **kw: "ran", tier, action=action)


@pytest.fixture
def policy():
    return PermissionPolicy.load(DEFAULT_POLICY_PATH)


class Asker:
    def __init__(self, answer):
        self.answer, self.questions = answer, []

    def __call__(self, question):
        self.questions.append(question)
        return self.answer


def test_real_policy_file_loads(policy):
    assert policy.decide("tasks.manage") == "allow"
    assert policy.decide("email.send") == "ask"
    assert policy.decide("payments") == "deny"


def test_unknown_action_is_ask(policy):
    assert policy.decide("rockets.launch") == "ask"


@pytest.mark.parametrize(
    "content",
    [None, "actions: [1, 2]", "{{ not yaml", "other: {}"],
)
def test_broken_or_missing_policy_fails_closed(tmp_path, content):
    path = tmp_path / "permissions.yaml"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    broken = PermissionPolicy.load(path)
    assert broken.decide("tasks.manage") == "ask"


def test_unknown_value_in_file_becomes_ask(tmp_path):
    path = tmp_path / "p.yaml"
    path.write_text("actions:\n  tasks.manage: maybe\n", encoding="utf-8")
    assert PermissionPolicy.load(path).decide("tasks.manage") == "ask"


def test_allow_runs_without_asking(policy):
    asker = Asker(False)
    decision = SafetyGate(policy, asker).check(tool(tier="personal", action="tasks.manage"), {})
    assert decision.allowed and asker.questions == []


def test_ask_runs_only_on_yes(policy):
    email = tool("send_email", "external", "email.send", "Send an email")
    yes, no = Asker(True), Asker(False)
    assert SafetyGate(policy, yes).check(email, {"to": "prof"}).allowed
    assert yes.questions == ["Rosie wants to send an email: send_email(to='prof')"]
    assert not SafetyGate(policy, no).check(email, {}).allowed


def test_ask_with_nobody_to_ask_is_no(policy):
    decision = SafetyGate(policy).check(tool(tier="external", action="email.send"), {})
    assert not decision.allowed
    assert "nobody could be asked" in decision.reason


@pytest.mark.parametrize("action", ["vault.user.write", "vault.user.delete", "payments"])
def test_deny_list_holds_even_if_user_would_say_yes(policy, action):
    asker = Asker(True)
    decision = SafetyGate(policy, asker).check(tool(tier="personal", action=action), {})
    assert not decision.allowed
    assert asker.questions == []  # never even asked


def test_tier_floor_beats_an_edited_allow():
    loose = PermissionPolicy({"email.send": "allow"})
    gate = SafetyGate(loose, Asker(False))
    assert not gate.check(tool(tier="external", action="email.send"), {}).allowed
    assert gate.decision_for(tool(tier="system", action="email.send")) == "ask"


def test_tools_without_action(policy):
    gate = SafetyGate(policy)
    assert gate.decision_for(tool(tier="read")) == "allow"
    assert gate.decision_for(tool(tier="personal")) == "ask"


def test_describe_call():
    assert describe_call(tool("x", description="Open an app."), {"name": "VS Code"}) == (
        "Rosie wants to open an app: x(name='VS Code')"
    )


def test_llm_cannot_bypass_the_deny_list_through_the_agent(policy):
    """Even if the model asks for a denied action directly, it never runs."""
    ran = []
    reg = ToolRegistry()
    reg.register(
        Tool(
            "edit_user_note",
            "Edit a note in the user's vault",
            lambda: ran.append(True),
            "personal",
            action="vault.user.write",
        )
    )

    class PushyLLM:
        def __init__(self):
            self.n = 0

        def chat(self, messages, tools=None):
            self.n += 1
            if tools is None:
                return ChatResult("I can't edit your vault.")
            return ChatResult(None, [ToolCall(str(self.n), "edit_user_note", {})])

    agent = Agent(PushyLLM(), reg, max_steps=3, gate=SafetyGate(policy, Asker(True)))
    result = agent.run([{"role": "user", "content": "edit my note"}])
    assert ran == []
    assert [s.status for s in result.steps] == ["refused"] * 3
    assert result.stopped == "step_cap"
