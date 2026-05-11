from __future__ import annotations

import requests

from file_logger import FileLogger
from .config import OnboardingConfig


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------
class OnboardingError(Exception):
    """Base exception for onboarding operations."""


class NetboxAPIError(OnboardingError):
    """Raised when a NetBox API call fails."""

    def __init__(self, status_code: int, response_body: str, endpoint: str = ""):
        self.status_code = status_code
        self.response_body = response_body
        self.endpoint = endpoint
        super().__init__(f"NetBox API error {status_code} on {endpoint}: {response_body}")


class ValidationError(OnboardingError):
    """Raised when data validation fails."""


class SpreadsheetError(OnboardingError):
    """Raised when CSV parsing fails."""


# ---------------------------------------------------------------------------
# NetBox API Client
# ---------------------------------------------------------------------------
class NetboxClient:
    """Generic HTTP client for the NetBox REST API."""

    def __init__(
        self,
        config: OnboardingConfig,
        session: requests.Session,
        logger: FileLogger,
    ) -> None:
        self._config = config
        self._session = session
        self._logger = logger
        self._headers = {
            "Authorization": f"Token {config.token}",
            "Content-Type": "application/json",
        }

    # -- helpers ----------------------------------------------------------

    def _url(self, endpoint: str) -> str:
        endpoint = endpoint.lstrip("/")
        return f"{self._config.url_api.rstrip('/')}/{endpoint}"

    # -- public API -------------------------------------------------------

    def get(self, endpoint: str) -> list[dict]:
        """Paginated GET — returns all results across pages."""
        all_results: list[dict] = []
        next_url: str | None = self._url(endpoint)

        while next_url:
            try:
                response = self._session.get(next_url, headers=self._headers, verify=False)
                response.raise_for_status()
                data = response.json()
                if "results" in data:
                    all_results.extend(data["results"])
                next_url = data.get("next")
            except requests.exceptions.RequestException as exc:
                status = getattr(exc.response, "status_code", None)
                body = getattr(exc.response, "text", str(exc))
                self._logger.error(
                    "GET failed",
                    endpoint=endpoint,
                    status=status,
                    body=body,
                )
                raise NetboxAPIError(status or 0, body, endpoint) from exc

        return all_results

    def get_single(self, endpoint: str) -> dict | None:
        """GET a single object. Returns None when not found (404)."""
        try:
            response = self._session.get(self._url(endpoint), headers=self._headers, verify=False)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            data = response.json()
            # If the response has a "results" key, return the first item
            if "results" in data:
                results = data["results"]
                return results[0] if results else None
            return data
        except requests.exceptions.RequestException as exc:
            status = getattr(exc.response, "status_code", None)
            body = getattr(exc.response, "text", str(exc))
            self._logger.error(
                "GET single failed",
                endpoint=endpoint,
                status=status,
                body=body,
            )
            return None

    def create(self, endpoint: str, data: dict | list[dict]) -> dict | list[dict] | None:
        """POST to create one or more objects. Returns the response JSON."""
        try:
            response = self._session.post(
                self._url(endpoint), headers=self._headers, json=data, verify=False
            )
            response.raise_for_status()
            self._logger.info("Object created", endpoint=endpoint)
            return response.json()
        except requests.exceptions.RequestException as exc:
            status = getattr(exc.response, "status_code", None)
            body = getattr(exc.response, "text", str(exc))
            self._logger.error(
                "POST failed",
                endpoint=endpoint,
                status=status,
                body=body,
            )
            return None

    def update(self, endpoint: str, data: dict) -> dict | None:
        """PATCH to update an existing object."""
        try:
            response = self._session.patch(
                self._url(endpoint), headers=self._headers, json=data, verify=False
            )
            response.raise_for_status()
            self._logger.info("Object updated", endpoint=endpoint)
            return response.json()
        except requests.exceptions.RequestException as exc:
            status = getattr(exc.response, "status_code", None)
            body = getattr(exc.response, "text", str(exc))
            self._logger.error(
                "PATCH failed",
                endpoint=endpoint,
                status=status,
                body=body,
            )
            return None

    def bulk_create(
        self, endpoint: str, items: list[dict], batch_size: int = 50
    ) -> list[dict]:
        """POST a list of objects in batches. Returns all created objects."""
        created: list[dict] = []
        for i in range(0, len(items), batch_size):
            batch = items[i : i + batch_size]
            result = self.create(endpoint, batch)
            if result:
                if isinstance(result, list):
                    created.extend(result)
                else:
                    created.append(result)
        return created
