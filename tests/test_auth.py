import json

import pytest

from meetily_detector.auth import (
    _load_client,
    build_token_record,
    exchange_code,
    save_token,
)


def test_load_client_installed(tmp_path):
    p = tmp_path / "client.json"
    p.write_text(json.dumps({"installed": {"client_id": "cid", "client_secret": "sec"}}))
    node = _load_client(str(p))
    assert node["client_id"] == "cid"


def test_load_client_rejects_bad_shape(tmp_path):
    p = tmp_path / "client.json"
    p.write_text(json.dumps({"nope": {}}))
    with pytest.raises(ValueError):
        _load_client(str(p))


def test_build_token_record_sets_expiry():
    body = {"access_token": "at", "refresh_token": "rt", "expires_in": 3600}
    rec = build_token_record(body, "cid", "sec", now=1000.0)
    assert rec == {
        "access_token": "at",
        "refresh_token": "rt",
        "client_id": "cid",
        "client_secret": "sec",
        "expiry": 4600.0,
    }


def test_save_token_roundtrip(tmp_path):
    path = tmp_path / "sub" / "token.json"
    rec = {"access_token": "at", "refresh_token": "rt", "expiry": 1.0}
    save_token(str(path), rec)
    assert json.loads(path.read_text())["access_token"] == "at"


def test_exchange_code_posts_expected_payload():
    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"access_token": "at", "refresh_token": "rt", "expires_in": 3600}

    class FakeSession:
        def post(self, url, data, timeout):
            captured["url"] = url
            captured["data"] = data
            return FakeResp()

    body = exchange_code(
        "https://token", "the-code", "cid", "sec", "http://127.0.0.1:5555/", session=FakeSession()
    )
    assert body["access_token"] == "at"
    assert captured["data"]["grant_type"] == "authorization_code"
    assert captured["data"]["code"] == "the-code"
    assert captured["data"]["redirect_uri"] == "http://127.0.0.1:5555/"
