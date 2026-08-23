"""Testes do cliente de e-mail (Resend)."""

import httpx
import pytest
from pydantic import SecretStr

from src.integrations.email_client import (
    API_URL,
    EmailAmbiguousError,
    EmailAuthError,
    EmailSendError,
    ResendClient,
)


class FakeClient:
    """Cliente HTTP falso para a API do Resend."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def post(self, url, json=None, headers=None, **kwargs):
        self.calls.append({"url": url, "json": json, "headers": headers})
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def response(status_code=200, body=None, text=None):
    request = httpx.Request("POST", API_URL)
    if text is not None:
        return httpx.Response(status_code=status_code, text=text, request=request)
    payload = {"id": "msg-123"} if body is None else body
    return httpx.Response(status_code=status_code, json=payload, request=request)


def make_client(responses):
    return ResendClient(
        api_key=SecretStr("re-teste"),
        sender="bot@exemplo.com",
        client=FakeClient(responses),
    )


def send(client):
    return client.send_message(
        recipient="rocha@exemplo.com",
        subject="Assunto",
        html="<p>oi</p>",
        text="oi",
    )


def test_sends_message_and_returns_id():
    fake = FakeClient([response()])
    client = ResendClient(api_key="re-plana", sender="bot@exemplo.com", client=fake)

    assert send(client) == "msg-123"
    assert fake.calls[0]["url"] == API_URL
    assert fake.calls[0]["headers"]["Authorization"] == "Bearer re-plana"
    assert fake.calls[0]["json"]["from"] == "bot@exemplo.com"
    assert fake.calls[0]["json"]["to"] == ["rocha@exemplo.com"]
    assert fake.calls[0]["json"]["html"] == "<p>oi</p>"
    assert fake.calls[0]["json"]["text"] == "oi"


def test_returns_empty_id_when_body_is_not_json():
    client = make_client([response(text="ok")])

    assert send(client) == ""


def test_returns_empty_id_when_body_is_a_list():
    client = make_client([response(body=[])])

    assert send(client) == ""


def test_auth_error_is_not_retried():
    fake = FakeClient([response(status_code=403)])
    client = ResendClient(api_key="re", sender="bot@exemplo.com", client=fake)

    with pytest.raises(EmailAuthError):
        send(client)
    assert len(fake.calls) == 1


def test_timeout_is_ambiguous_and_never_retried():
    fake = FakeClient([httpx.TimeoutException("timeout")])
    client = ResendClient(api_key="re", sender="bot@exemplo.com", client=fake)

    with pytest.raises(EmailAmbiguousError):
        send(client)
    assert len(fake.calls) == 1


def test_retries_transient_status_then_succeeds():
    fake = FakeClient([response(status_code=429), response()])
    client = ResendClient(api_key="re", sender="bot@exemplo.com", client=fake)

    assert send(client) == "msg-123"
    assert len(fake.calls) == 2


def test_gives_up_after_repeated_server_errors():
    client = make_client([response(status_code=502)] * 3)

    with pytest.raises(EmailSendError, match="Não foi possível enviar"):
        send(client)


def test_raises_on_permanent_client_error():
    client = make_client([response(status_code=422)])

    with pytest.raises(EmailSendError, match="HTTP 422"):
        send(client)


def test_retries_transport_error_then_gives_up():
    client = make_client([httpx.ConnectError("sem rede")] * 3)

    with pytest.raises(EmailSendError, match="Não foi possível enviar"):
        send(client)


def test_uses_module_level_httpx_when_no_client(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: response())
    client = ResendClient(api_key="re", sender="bot@exemplo.com")

    assert send(client) == "msg-123"
