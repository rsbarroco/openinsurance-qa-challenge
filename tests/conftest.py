"""Starter conftest for the DocExtract eval harness.

Add shared fixtures here (e.g., a FastAPI TestClient, ground-truth loaders,
helpers for running N extractions per document). The repo ships with this
file intentionally minimal — the test suite is yours to design.

Example starting point:

    from fastapi.testclient import TestClient
    import pytest
    from app.main import app

    @pytest.fixture(scope="session")
    def client() -> TestClient:
        return TestClient(app)
"""
