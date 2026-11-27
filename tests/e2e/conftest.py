from __future__ import annotations

from collections.abc import Iterator

import pytest
from rosie_fakes import FakeModel, start_http, stop_http


@pytest.fixture
def model_url() -> Iterator[str]:
    """The fake model's OpenAI-compatible base URL (see rosie_fakes.py)."""
    model = start_http(FakeModel)
    try:
        yield f"http://127.0.0.1:{model.server_address[1]}/v1"
    finally:
        stop_http(model)
