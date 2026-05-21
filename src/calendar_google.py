"""Cliente para Google Calendar API.

Auth: OAuth 2.0 con refresh_token long-lived obtenido una sola vez con
`scripts/google_oauth_setup.py`. Las credenciales viven en .env, no en disco.

Docs: https://developers.google.com/calendar/api/v3/reference/events/insert
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from . import config

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
TOKEN_URI = "https://oauth2.googleapis.com/token"


class CalendarError(RuntimeError):
    """Error envolviendo fallas de la API o configuración."""

    def __init__(self, message: str, status: int | None = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


def _ensure_config() -> None:
    faltantes = [
        name
        for name, val in (
            ("GOOGLE_CALENDAR_CLIENT_ID", config.GOOGLE_CALENDAR_CLIENT_ID),
            ("GOOGLE_CALENDAR_CLIENT_SECRET", config.GOOGLE_CALENDAR_CLIENT_SECRET),
            ("GOOGLE_CALENDAR_REFRESH_TOKEN", config.GOOGLE_CALENDAR_REFRESH_TOKEN),
        )
        if not val
    ]
    if faltantes:
        raise CalendarError(
            f"Faltan env vars de Google Calendar: {', '.join(faltantes)}. "
            "Correr scripts/google_oauth_setup.py para obtener el refresh_token."
        )


def _get_service():
    _ensure_config()
    creds = Credentials(
        token=None,
        refresh_token=config.GOOGLE_CALENDAR_REFRESH_TOKEN,
        client_id=config.GOOGLE_CALENDAR_CLIENT_ID,
        client_secret=config.GOOGLE_CALENDAR_CLIENT_SECRET,
        token_uri=TOKEN_URI,
        scopes=SCOPES,
    )
    # Fuerza un refresh para obtener access_token fresco antes del request.
    creds.refresh(GoogleRequest())
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def crear_evento(
    *,
    titulo: str,
    descripcion: str,
    inicio_iso: str,
    duracion_min: int,
    invitados_emails: list[str] | None = None,
) -> dict[str, Any]:
    """Crea un evento con Google Meet auto-generado.

    `inicio_iso` debe ser un timestamp ISO 8601 en hora local del timezone
    configurado (ej '2026-05-25T15:00:00'). Sin offset, se asume el
    `GOOGLE_CALENDAR_TIMEZONE` del .env.
    """
    try:
        inicio_dt = datetime.fromisoformat(inicio_iso)
    except ValueError as e:
        raise CalendarError(f"fecha_hora_iso inválida: {inicio_iso} ({e})")

    fin_dt = inicio_dt + timedelta(minutes=duracion_min)
    tz = config.GOOGLE_CALENDAR_TIMEZONE

    body: dict[str, Any] = {
        "summary": titulo,
        "description": descripcion,
        "start": {"dateTime": inicio_dt.isoformat(), "timeZone": tz},
        "end": {"dateTime": fin_dt.isoformat(), "timeZone": tz},
        "conferenceData": {
            "createRequest": {
                "requestId": uuid4().hex,
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
    }
    if invitados_emails:
        body["attendees"] = [{"email": e} for e in invitados_emails if e]

    service = _get_service()
    try:
        evento = (
            service.events()
            .insert(
                calendarId=config.GOOGLE_CALENDAR_ID,
                body=body,
                conferenceDataVersion=1,
                sendUpdates="all" if invitados_emails else "none",
            )
            .execute()
        )
    except HttpError as e:
        raise CalendarError(
            f"Google Calendar API error: {e.reason}",
            status=e.resp.status if e.resp else None,
            body=getattr(e, "error_details", None),
        ) from e

    meet_link = None
    for entry in evento.get("conferenceData", {}).get("entryPoints", []) or []:
        if entry.get("entryPointType") == "video":
            meet_link = entry.get("uri")
            break

    return {
        "event_id": evento.get("id"),
        "html_link": evento.get("htmlLink"),
        "meet_link": meet_link,
        "inicio": evento.get("start", {}).get("dateTime"),
        "fin": evento.get("end", {}).get("dateTime"),
        "timezone": tz,
    }
