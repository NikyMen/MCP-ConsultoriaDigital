"""Cliente HTTP para Kommo CRM (API v4).

Auth: long-lived access token (Bearer) generado desde
  Configuración → Integraciones → Crear integración (privada).

Docs: https://developers.kommo.com/reference
"""
from __future__ import annotations

from typing import Any

import httpx

from . import config


class KommoError(RuntimeError):
    """Error envolviendo respuestas no exitosas de la API."""

    def __init__(self, status: int, message: str, body: Any = None):
        super().__init__(f"Kommo {status}: {message}")
        self.status = status
        self.body = body


def _ensure_config() -> None:
    if not config.KOMMO_SUBDOMAIN or not config.KOMMO_ACCESS_TOKEN:
        raise KommoError(
            0,
            "KOMMO_SUBDOMAIN y KOMMO_ACCESS_TOKEN deben estar configurados en .env",
        )


def _base_url() -> str:
    return f"https://{config.KOMMO_SUBDOMAIN}.kommo.com"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.KOMMO_ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _request(method: str, path: str, *, params: dict | None = None, json: Any = None) -> Any:
    _ensure_config()
    url = f"{_base_url()}{path}"
    with httpx.Client(timeout=20.0) as client:
        r = client.request(method, url, headers=_headers(), params=params, json=json)
    if r.status_code == 204 or not r.content:
        return None
    try:
        body = r.json()
    except ValueError:
        body = r.text
    if r.status_code >= 400:
        raise KommoError(r.status_code, str(body)[:500], body)
    return body


# ---------------------------------------------------------------------------
# Pipelines & statuses
# ---------------------------------------------------------------------------

def listar_pipelines() -> list[dict[str, Any]]:
    """Devuelve los pipelines con sus statuses anidados (simplificados)."""
    data = _request("GET", "/api/v4/leads/pipelines") or {}
    pipelines = data.get("_embedded", {}).get("pipelines", [])
    salida = []
    for p in pipelines:
        statuses = p.get("_embedded", {}).get("statuses", [])
        salida.append(
            {
                "id": p["id"],
                "name": p.get("name"),
                "is_main": p.get("is_main"),
                "is_archive": p.get("is_archive"),
                "statuses": [
                    {
                        "id": s["id"],
                        "name": s.get("name"),
                        "sort": s.get("sort"),
                        "color": s.get("color"),
                        "type": s.get("type"),  # 0 normal, 1 won, 2 lost
                    }
                    for s in statuses
                ],
            }
        )
    return salida


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def listar_usuarios() -> list[dict[str, Any]]:
    data = _request("GET", "/api/v4/users") or {}
    users = data.get("_embedded", {}).get("users", [])
    return [
        {
            "id": u["id"],
            "name": u.get("name"),
            "email": u.get("email"),
            "lang": u.get("lang"),
        }
        for u in users
    ]


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------

def buscar_leads(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Busca leads por texto libre (nombre, teléfono, email, etc.)."""
    data = _request(
        "GET",
        "/api/v4/leads",
        params={"query": query, "limit": min(limit, 50), "with": "contacts"},
    )
    if not data:
        return []
    return data.get("_embedded", {}).get("leads", [])


def obtener_lead(lead_id: int) -> dict[str, Any] | None:
    try:
        return _request("GET", f"/api/v4/leads/{lead_id}", params={"with": "contacts"})
    except KommoError as e:
        if e.status == 404:
            return None
        raise


def crear_lead_complejo(
    *,
    name: str,
    pipeline_id: int | None = None,
    status_id: int | None = None,
    responsible_user_id: int | None = None,
    price: int | None = None,
    contacto_nombre: str | None = None,
    contacto_telefono: str | None = None,
    contacto_email: str | None = None,
    empresa_nombre: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """
    Crea un lead con contacto (y opcionalmente compañía) en una sola llamada
    usando POST /api/v4/leads/complex.

    Devuelve el primer lead creado (la API responde un array).
    """
    lead: dict[str, Any] = {"name": name}
    if pipeline_id:
        lead["pipeline_id"] = pipeline_id
    if status_id:
        lead["status_id"] = status_id
    if responsible_user_id:
        lead["responsible_user_id"] = responsible_user_id
    if price is not None:
        lead["price"] = price
    if tags:
        lead["_embedded"] = {"tags": [{"name": t} for t in tags]}

    embedded: dict[str, Any] = lead.setdefault("_embedded", {})

    if contacto_telefono or contacto_email or contacto_nombre:
        cf: list[dict[str, Any]] = []
        if contacto_telefono:
            cf.append(
                {
                    "field_code": "PHONE",
                    "values": [{"value": contacto_telefono, "enum_code": "WORK"}],
                }
            )
        if contacto_email:
            cf.append(
                {
                    "field_code": "EMAIL",
                    "values": [{"value": contacto_email, "enum_code": "WORK"}],
                }
            )
        contact: dict[str, Any] = {"name": contacto_nombre or name}
        if cf:
            contact["custom_fields_values"] = cf
        embedded["contacts"] = [contact]

    if empresa_nombre:
        embedded["companies"] = [{"name": empresa_nombre}]

    data = _request("POST", "/api/v4/leads/complex", json=[lead])
    if isinstance(data, list) and data:
        return data[0]
    return data or {}


def actualizar_lead(
    lead_id: int,
    *,
    name: str | None = None,
    pipeline_id: int | None = None,
    status_id: int | None = None,
    responsible_user_id: int | None = None,
    price: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if name is not None:
        payload["name"] = name
    if pipeline_id is not None:
        payload["pipeline_id"] = pipeline_id
    if status_id is not None:
        payload["status_id"] = status_id
    if responsible_user_id is not None:
        payload["responsible_user_id"] = responsible_user_id
    if price is not None:
        payload["price"] = price
    if not payload:
        raise KommoError(0, "actualizar_lead requiere al menos un campo")
    return _request("PATCH", f"/api/v4/leads/{lead_id}", json=payload) or {}


def agregar_nota(lead_id: int, texto: str) -> dict[str, Any]:
    payload = [{"note_type": "common", "params": {"text": texto}}]
    return _request("POST", f"/api/v4/leads/{lead_id}/notes", json=payload) or {}


def crear_tarea(
    *,
    lead_id: int,
    texto: str,
    complete_till_unix: int,
    responsible_user_id: int | None = None,
    task_type_id: int | None = None,
) -> dict[str, Any]:
    task: dict[str, Any] = {
        "entity_id": lead_id,
        "entity_type": "leads",
        "text": texto,
        "complete_till": complete_till_unix,
    }
    if responsible_user_id:
        task["responsible_user_id"] = responsible_user_id
    if task_type_id:
        task["task_type_id"] = task_type_id
    return _request("POST", "/api/v4/tasks", json=[task]) or {}
