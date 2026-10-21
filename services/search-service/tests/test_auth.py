"""Tests for the authentication middleware."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.config import AppConfig, AuthConfig, MeiliSearchConfig, SQSConfig
from app.main import create_app

SERVICE_TOKEN = "test-service-token"


def _make_client(mock_meilisearch_client: MagicMock, auth: AuthConfig):
    config = AppConfig(
        meilisearch=MeiliSearchConfig(url="http://localhost:7700"),
        sqs=SQSConfig(enabled=False),
        auth=auth,
    )
    with patch("app.services.meilisearch_client.meilisearch.Client") as mock_cls:
        mock_cls.return_value = mock_meilisearch_client
        app = create_app(config)
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture()
def secured_client(mock_meilisearch_client: MagicMock):
    return _make_client(
        mock_meilisearch_client, AuthConfig(service_token=SERVICE_TOKEN, require_auth=True)
    )


class TestAuthMiddleware:
    @pytest.mark.parametrize("path", ["/health", "/health/ready", "/metrics"])
    def test_public_paths_do_not_require_auth(self, secured_client, path):
        assert secured_client.get(path).status_code in (200, 503)

    def test_missing_credentials_rejected(self, secured_client):
        response = secured_client.get("/api/v1/search/?q=test")
        assert response.status_code == 401
        assert response.get_json() == {"error": "unauthorized"}

    def test_gateway_user_header_accepted(self, secured_client):
        response = secured_client.get("/api/v1/search/?q=test", headers={"X-User-ID": "user-1"})
        assert response.status_code == 200

    def test_blank_user_header_rejected(self, secured_client):
        response = secured_client.get("/api/v1/search/?q=test", headers={"X-User-ID": "   "})
        assert response.status_code == 401

    def test_valid_service_token_accepted(self, secured_client):
        response = secured_client.post(
            "/api/v1/search/reindex", headers={"Authorization": f"Bearer {SERVICE_TOKEN}"}
        )
        assert response.status_code == 200

    def test_bearer_scheme_is_case_insensitive(self, secured_client):
        response = secured_client.post(
            "/api/v1/search/reindex", headers={"Authorization": f"bearer {SERVICE_TOKEN}"}
        )
        assert response.status_code == 200

    def test_wrong_service_token_rejected(self, secured_client):
        response = secured_client.post(
            "/api/v1/search/reindex", headers={"Authorization": "Bearer wrong"}
        )
        assert response.status_code == 401

    def test_non_bearer_authorization_rejected(self, secured_client):
        response = secured_client.post(
            "/api/v1/search/reindex", headers={"Authorization": f"Basic {SERVICE_TOKEN}"}
        )
        assert response.status_code == 401

    def test_token_ignored_when_not_configured(self, mock_meilisearch_client):
        client = _make_client(mock_meilisearch_client, AuthConfig(service_token="", require_auth=True))
        response = client.post("/api/v1/search/reindex", headers={"Authorization": "Bearer "})
        assert response.status_code == 401

    def test_auth_disabled_allows_anonymous(self, mock_meilisearch_client):
        client = _make_client(mock_meilisearch_client, AuthConfig(service_token="", require_auth=False))
        assert client.get("/api/v1/search/?q=test").status_code == 200
