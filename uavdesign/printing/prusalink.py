"""Read-only PrusaLink adapter; never uploads files or changes printer state.

API reference: https://github.com/prusa3d/Prusa-Link-Web/blob/master/spec/openapi.yaml
Credentials use the documented HTTP Digest mechanism. They are supplied only
through environment variables, never serialized into a plan or status snapshot.
"""

from __future__ import annotations

import json
import math
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import (
    HTTPDigestAuthHandler, HTTPPasswordMgrWithDefaultRealm, HTTPRedirectHandler,
    ProxyHandler, Request, build_opener,
)


class PrusaLinkError(RuntimeError):
    """A configuration or connection error with no credential-bearing details."""


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise PrusaLinkError("PrusaLink redirects are disabled")


class PrusaLink:
    """An explicitly configured LAN endpoint with a bounded GET-only interface."""

    ENDPOINTS = {
        "version": "/api/version", "info": "/api/v1/info",
        "status": "/api/v1/status", "storage": "/api/v1/storage",
        "job": "/api/v1/job",
    }

    def __init__(self, url: str, username: str, password: str, *, timeout_s: float = 5):
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError:
            raise PrusaLinkError("Invalid PRUSALINK_URL") from None
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or parsed.path not in {"", "/"}
                or any(ch.isspace() for ch in url)
                or (port is not None and not 1 <= port <= 65535)):
            raise PrusaLinkError("PRUSALINK_URL must be an HTTP(S) origin without credentials, path or query")
        if not username or not password or any(ch in username + password for ch in "\r\n\x00"):
            raise PrusaLinkError("PrusaLink username and password must be nonempty and contain no control separators")
        if isinstance(timeout_s, bool) or not math.isfinite(timeout_s) or not 0 < timeout_s <= 10:
            raise PrusaLinkError("PrusaLink per-request timeout must be greater than zero and at most 10 seconds")
        self.url = url.rstrip("/")
        self.timeout_s = timeout_s
        self._secrets = (password, username)
        passwords = HTTPPasswordMgrWithDefaultRealm()
        passwords.add_password(None, self.url, username, password)
        # Local printer traffic must not carry credentials to an environment proxy.
        self._opener = build_opener(ProxyHandler({}), _NoRedirects(), HTTPDigestAuthHandler(passwords))

    @classmethod
    def from_environment(cls, *, timeout_s: float = 5) -> "PrusaLink":
        names = ("PRUSALINK_URL", "PRUSALINK_USERNAME", "PRUSALINK_PASSWORD")
        if any(not os.environ.get(name) for name in names):
            raise PrusaLinkError("Set PRUSALINK_URL, PRUSALINK_USERNAME and PRUSALINK_PASSWORD for read-only printer status")
        return cls(*(os.environ[name] for name in names), timeout_s=timeout_s)

    def _redact(self, value):
        if isinstance(value, dict):
            return {
                key: "[redacted]" if any(word in str(key).lower().replace("-", "").replace("_", "")
                                         for word in ("password", "token", "apikey", "authorization", "secret"))
                else self._redact(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        if isinstance(value, str):
            for secret in self._secrets:
                value = value.replace(secret, "[redacted]")
        return value

    def _get(self, endpoint: str):
        if endpoint not in self.ENDPOINTS.values():
            raise PrusaLinkError("Unsupported read-only PrusaLink endpoint")
        request = Request(self.url + endpoint, headers={"Accept": "application/json"}, method="GET")
        with self._opener.open(request, timeout=self.timeout_s) as response:
            if response.status == 204:
                return None
            if response.status != 200:
                raise PrusaLinkError("Unexpected PrusaLink response status")
            payload = response.read(1_048_577)
        if len(payload) > 1_048_576:
            raise PrusaLinkError("PrusaLink response exceeds size limit")
        value = json.loads(payload)
        if not isinstance(value, dict):
            raise PrusaLinkError("PrusaLink response is not a JSON object")
        return self._redact(value)

    def status_snapshot(self) -> dict:
        """Probe fixed GET endpoints; expose explicit errors and never infer readiness.

        At most five requests are made, each limited to ``timeout_s``. A 204 job
        response means no job. HTTP errors and malformed responses remain visible
        as sanitized endpoint errors, not fabricated empty printer data.
        """
        results, errors = {}, {}
        for name, endpoint in self.ENDPOINTS.items():
            try:
                value = self._get(endpoint)
                if value is None and name != "job":
                    raise PrusaLinkError("Required endpoint returned no content")
                results[name] = value
            except HTTPError as exc:
                errors[name] = {"kind": "http_error", "status": int(exc.code)}
            except (URLError, TimeoutError, OSError):
                errors[name] = {"kind": "connection_error"}
            except (ValueError, UnicodeError, PrusaLinkError):
                errors[name] = {"kind": "invalid_or_rejected_response"}
        required = {"version", "status", "storage"}
        state = "available" if not errors else "partial" if required <= results.keys() else "unavailable"
        return {"adapter": "prusalink", "read_only": True, "state": state,
                "endpoint": self.url, "data": results, "errors": errors,
                "print_ready": None}
