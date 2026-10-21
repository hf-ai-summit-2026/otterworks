from __future__ import annotations

import math
import os
import re
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from .config import (
    Credentials,
    delete_credentials,
    load_credentials,
    resolve_api_url,
    save_credentials,
)


def normalize_keys(value: Any) -> Any:
    if isinstance(value, list):
        return [normalize_keys(item) for item in value]
    if isinstance(value, dict):
        return {
            re.sub(r"_([a-z])", lambda match: match.group(1).upper(), key): normalize_keys(
                item
            )
            for key, item in value.items()
        }
    return value


class ApiError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"HTTP {status_code}: {message}")


class SessionExpiredError(Exception):
    def __init__(self) -> None:
        super().__init__("Session expired, run `otter login`.")


class OtterClient:
    def __init__(
        self,
        api_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
        credentials: Credentials | None = None,
    ) -> None:
        self._environment_token = os.environ.get("OTTER_TOKEN")
        self.credentials = (
            None
            if self._environment_token
            else credentials if credentials is not None else load_credentials()
        )
        self.api_url = resolve_api_url(api_url, self.credentials)
        self.access_token = self._environment_token or (
            self.credentials.access_token if self.credentials else ""
        )
        self.refresh_token = (
            self.credentials.refresh_token
            if self.credentials and not self._environment_token
            else ""
        )
        self.email = self.credentials.email if self.credentials else ""
        self._http = httpx.Client(
            base_url=self.api_url,
            timeout=30,
            transport=transport,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._http.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        use_access_token: bool = True,
        **kwargs: Any,
    ) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}))
        if use_access_token and self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        api_path = (
            path
            if path.startswith(("http://", "https://"))
            else f"/api/v1{path}"
        )
        return self._http.request(method, api_path, headers=headers, **kwargs)

    @staticmethod
    def _decode(response: httpx.Response) -> Any:
        try:
            return normalize_keys(response.json())
        except (ValueError, TypeError):
            return response.content

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.is_success:
            return
        try:
            data = normalize_keys(response.json()) if response.content else {}
        except (ValueError, TypeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        message = (
            data.get("message")
            or data.get("error")
            or response.reason_phrase
            or "Request failed"
        )
        raise ApiError(response.status_code, str(message))

    def _persist_tokens(self) -> None:
        if self._environment_token:
            return
        self.credentials = Credentials(
            api_url=self.api_url,
            email=self.email,
            access_token=self.access_token,
            refresh_token=self.refresh_token,
        )
        save_credentials(self.credentials)

    def _refresh(self) -> None:
        if not self.refresh_token:
            raise SessionExpiredError()
        try:
            response = self._request(
                "POST",
                "/auth/refresh",
                use_access_token=False,
                headers={"Authorization": f"Bearer {self.refresh_token}"},
            )
        except httpx.HTTPError as error:
            raise SessionExpiredError() from error
        if not response.is_success:
            raise SessionExpiredError()
        data = self._decode(response)
        if not isinstance(data, dict):
            raise SessionExpiredError()
        access_token = data.get("accessToken")
        refresh_token = data.get("refreshToken")
        if not access_token or not refresh_token:
            raise SessionExpiredError()
        self.access_token = str(access_token)
        self.refresh_token = str(refresh_token)
        self._persist_tokens()

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._request(method, path, **kwargs)
        if response.status_code == 401 and not path.startswith("/auth/"):
            self._refresh()
            for value in (kwargs.get("files") or {}).values():
                stream = value[1] if isinstance(value, tuple) and len(value) > 1 else value
                if hasattr(stream, "seek"):
                    stream.seek(0)
            response = self._request(method, path, **kwargs)
        self._raise_for_status(response)
        if response.status_code == 204 or not response.content:
            return None
        return self._decode(response)

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> Any:
        return self.request("PUT", path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> Any:
        return self.request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self.request("DELETE", path, **kwargs)

    def login(self, email: str, password: str) -> dict[str, Any]:
        response = self._request(
            "POST", "/auth/login", json={"email": email, "password": password}
        )
        self._raise_for_status(response)
        data = self._decode(response)
        if not isinstance(data, dict):
            raise TypeError("Login returned an invalid response")
        access_token = data.get("accessToken")
        refresh_token = data.get("refreshToken")
        if not access_token or not refresh_token:
            raise ValueError("Login response did not include access and refresh tokens")
        self.email = email
        self.access_token = str(access_token)
        self.refresh_token = str(refresh_token)
        self._persist_tokens()
        return data

    def logout(self) -> None:
        try:
            self.post("/auth/logout")
        except (ApiError, SessionExpiredError, httpx.HTTPError):
            pass
        delete_credentials()

    def list_all_files(
        self, folder_id: str | None = None, endpoint: str = "/files"
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"page": 1, "page_size": 1000}
        if folder_id is not None:
            params["folder_id"] = folder_id
        first_response = self.get(endpoint, params=params)
        files = list(first_response.get("files", []))
        total = int(first_response.get("total", len(files)))
        page_size = max(1, int(first_response.get("pageSize", 1000)))
        page_count = math.ceil(total / page_size)
        if page_count <= 1:
            return files[:total]

        def get_page(page: int) -> list[dict[str, Any]]:
            page_params = dict(params, page=page)
            response = self.get(endpoint, params=page_params)
            return list(response.get("files", []))

        with ThreadPoolExecutor(max_workers=min(8, page_count - 1)) as executor:
            for page_files in executor.map(get_page, range(2, page_count + 1)):
                files.extend(page_files)
        return files[:total]

    def list_folder_tree(self) -> list[dict[str, Any]]:
        folders: list[dict[str, Any]] = []
        pending: list[str | None] = [None]
        seen: set[str] = set()
        while pending:
            parent_id = pending.pop(0)
            params = {"parent_id": parent_id} if parent_id else {}
            response = self.get("/folders", params=params)
            children = response.get("folders", [])
            for folder in children:
                folder_id = str(folder.get("id", ""))
                if folder_id in seen:
                    continue
                seen.add(folder_id)
                folders.append(folder)
                pending.append(folder_id)
        return folders

    def stream_download(self, url: str) -> Iterator[bytes]:
        download_host = os.environ.get("OTTER_DOWNLOAD_HOST")
        if download_host:
            parts = urlsplit(url)
            url = urlunsplit(
                (parts.scheme, download_host, parts.path, parts.query, parts.fragment)
            )
        with self._http.stream("GET", url, timeout=60) as response:
            if not response.is_success:
                response.read()
            self._raise_for_status(response)
            yield from response.iter_bytes()

    def download_to(self, url: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as output:
            for chunk in self.stream_download(url):
                output.write(chunk)
