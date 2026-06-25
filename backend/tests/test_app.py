"""
ExamShield — Basic test suite for CI/CD pipeline.
These tests validate the app starts and core routes respond.
"""
import pytest
import os
import sys

# Ensure backend/ is on path when run from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app as flask_app


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    with flask_app.test_client() as client:
        yield client


def test_health_endpoint(client):
    """CloudWatch and ALB target groups hit /health."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.get_json()
    assert data is not None
    assert data.get("status") == "ok"


def test_root_returns_200_or_redirect(client):
    """Landing page or redirect — should not 500."""
    response = client.get("/")
    assert response.status_code in (200, 301, 302)


def test_login_page_loads(client):
    """University portal must be reachable (GET)."""
    response = client.get("/university")
    assert response.status_code in (200, 301, 302)

def test_404_handled(client):
    """App should return 404 for unknown routes, not crash."""
    response = client.get("/this-route-does-not-exist-xyz")
    assert response.status_code == 404
