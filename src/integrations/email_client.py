"""Cliente de envio de e-mail via API do Resend."""

import logging
import time

import httpx
from pydantic import SecretStr

logger = logging.getLogger(__name__)

API_URL = "https://api.resend.com/emails"
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 2.0
REQUEST_TIMEOUT = 30.0


class EmailSendError(RuntimeError):
    """Falha no envio do e-mail."""


class EmailAuthError(EmailSendError):
    """Credencial do Resend inválida ou sem permissão."""


class EmailAmbiguousError(EmailSendError):
    """Falha ambígua: o provedor pode ou não ter aceitado a mensagem."""


class ResendClient:
    """Envia e-mails pela API do Resend, isolando o HTTP do resto da aplicação."""

    def __init__(
        self,
        api_key: SecretStr | str,
        sender: str,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key.get_secret_value() if isinstance(api_key, SecretStr) else api_key
        self._sender = sender
        self._client = client

    def send_message(self, recipient: str, subject: str, html: str, text: str) -> str:
        """Envia o digest e devolve o id da mensagem aceita pelo provedor."""
        payload = {
            "from": self._sender,
            "to": [recipient],
            "subject": subject,
            "html": html,
            "text": text,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self._post(payload, headers)
            except httpx.TimeoutException as exc:
                # O provedor pode ter recebido a mensagem: não reenviar às cegas.
                raise EmailAmbiguousError(
                    "Timeout ao enviar o e-mail; o envio pode ter ocorrido. "
                    "Nenhuma retentativa automática foi feita."
                ) from exc
            except httpx.TransportError as exc:
                last_error = exc
                logger.warning("Email request failed (attempt %d/%d)", attempt, MAX_RETRIES)
                if attempt < MAX_RETRIES:
                    time.sleep(BACKOFF_BASE_SECONDS * 2 ** (attempt - 1))
                continue

            if response.status_code in (401, 403):
                raise EmailAuthError("Credencial do Resend inválida ou sem permissão")

            if response.status_code == 429 or response.status_code >= 500:
                last_error = EmailSendError(f"Status transitório {response.status_code}")
                logger.warning(
                    "Resend returned %d (attempt %d/%d)",
                    response.status_code,
                    attempt,
                    MAX_RETRIES,
                )
                if attempt < MAX_RETRIES:
                    time.sleep(BACKOFF_BASE_SECONDS * 2 ** (attempt - 1))
                continue

            if response.status_code >= 400:
                raise EmailSendError(f"Erro do Resend: HTTP {response.status_code}")

            return _extract_id(response)

        raise EmailSendError(f"Não foi possível enviar o e-mail: {last_error}")

    def _post(self, payload: dict, headers: dict) -> httpx.Response:
        if self._client is not None:
            return self._client.post(
                API_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT
            )
        return httpx.post(API_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)


def _extract_id(response: httpx.Response) -> str:
    """Lê o id da mensagem na resposta do Resend, quando disponível."""
    try:
        body = response.json()
    except ValueError:
        return ""
    return str(body.get("id", "")) if isinstance(body, dict) else ""
