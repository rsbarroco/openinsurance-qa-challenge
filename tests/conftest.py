from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eval.harness import create_eval_client


@pytest.fixture(scope="session")
def eval_client() -> TestClient:
    return create_eval_client(disable_noise=True)
