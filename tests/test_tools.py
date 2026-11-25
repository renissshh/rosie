import pytest

from rosie.tools import Tool, ToolError, ToolRegistry

ADD_TASK_PARAMS = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "priority": {"type": "integer"},
        "area": {"type": "string", "enum": ["study", "gym", "life"]},
    },
    "required": ["title"],
}


@pytest.fixture
def registry():
    reg = ToolRegistry()

    @reg.tool("add_task", "Add a task", tier="personal", parameters=ADD_TASK_PARAMS)
    def add_task(title, priority=2, area="life"):
        return f"added {title} p{priority} {area}"

    @reg.tool("get_time", "Current time")
    def get_time():
        return "23:59"

    return reg


def test_schemas_are_openai_format_and_sorted(registry):
    schemas = registry.schemas()
    assert [s["function"]["name"] for s in schemas] == ["add_task", "get_time"]
    assert schemas[0]["type"] == "function"
    assert schemas[0]["function"]["parameters"] == ADD_TASK_PARAMS
    assert schemas[1]["function"]["parameters"]["properties"] == {}


def test_call_runs_handler(registry):
    assert registry.call("add_task", {"title": "DBMS", "priority": 1}) == "added DBMS p1 life"
    assert registry.call("get_time", {}) == "23:59"


def test_tier_is_kept(registry):
    assert registry.get("add_task").tier == "personal"
    assert registry.get("get_time").tier == "read"


@pytest.mark.parametrize(
    "args, message",
    [
        ({}, "missing argument 'title'"),
        ({"title": "x", "due": "today"}, "unknown argument 'due'"),
        ({"title": 5}, "should be string"),
        ({"title": "x", "priority": "high"}, "should be integer"),
        ({"title": "x", "priority": True}, "should be integer"),
        ({"title": "x", "area": "party"}, "must be one of"),
    ],
)
def test_invalid_arguments_rejected(registry, args, message):
    with pytest.raises(ToolError, match=message):
        registry.call("add_task", args)


def test_unknown_tool(registry):
    with pytest.raises(ToolError, match="unknown tool 'fly'"):
        registry.call("fly", {})


def test_duplicate_registration_rejected(registry):
    with pytest.raises(ValueError, match="already registered"):
        registry.register(Tool("get_time", "dup", lambda: None))


def test_handler_crash_becomes_tool_error():
    reg = ToolRegistry()
    reg.register(Tool("boom", "fails", lambda: 1 / 0))
    with pytest.raises(ToolError, match="boom failed"):
        reg.call("boom", {})


def test_none_result_becomes_empty_string():
    reg = ToolRegistry()
    reg.register(Tool("noop", "nothing", lambda: None))
    assert reg.call("noop", {}) == ""
