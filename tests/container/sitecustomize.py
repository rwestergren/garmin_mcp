"""Fake Garmin responses while retaining real token loading and refresh logic."""

import base64
import json
import time

from garminconnect.client import Client


def token(expires):
    payload = base64.urlsafe_b64encode(json.dumps({"exp": expires}).encode()).decode().rstrip("=")
    return f"test.{payload}.signature"


class Response:
    status_code = 200
    ok = True

    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


class Session:
    def request(self, method, url, **kwargs):
        if url.endswith("/socialProfile"):
            return Response({"displayName": "smoke-user", "fullName": "Smoke User"})
        if url.endswith("/user-settings"):
            return Response({"userData": {"measurementSystem": "metric"}})
        if url.endswith("/devices"):
            return Response([{"displayName": "Smoke watch"}])
        raise AssertionError(f"Unexpected Garmin request: {method} {url}")


def refresh(self, url, **kwargs):
    assert kwargs["data"]["grant_type"] == "refresh_token"
    assert kwargs["data"]["refresh_token"] == "original-refresh"
    return Response({"access_token": token(time.time() + 86400), "refresh_token": "rotated-refresh"})


def no_password_login(*args, **kwargs):
    raise AssertionError("Password login must not run")


Client._fresh_api_session = lambda self: Session()
Client._http_post = refresh
Client.login = no_password_login
