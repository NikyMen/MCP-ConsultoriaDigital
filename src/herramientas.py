"""Metadata de las herramientas (tools) MCP para el panel de administración.

La lista *viva* de tools se introspecta del servidor FastMCP en tiempo de
request (ver ``admin.herramientas``). Acá vive solo lo que no se puede deducir
del código: a qué **grupo** pertenece cada tool y qué **configuración** del
``.env`` necesita ese grupo para funcionar.

Para sumar una tool nueva al panel: registrala con ``@mcp.tool`` en server.py y,
si pertenece a un grupo nuevo, agregá el grupo en ``GRUPOS`` y mapeá su nombre
en ``TOOL_GRUPO``. Si cae en un grupo existente no hace falta tocar nada: las
tools sin mapear se muestran bajo "Otras".
"""
from __future__ import annotations

from typing import Any, Callable

from . import config

# ---------------------------------------------------------------------------
# Definición de grupos
# ---------------------------------------------------------------------------
# Cada grupo describe:
#   clave        : id interno
#   nombre       : título visible
#   descripcion  : para qué sirve el conjunto
#   requisitos   : función que devuelve la lista de requisitos de .env
#                  [(etiqueta, presente: bool, opcional: bool), ...]
#                  Si devuelve [] el grupo está siempre disponible (sin config).


def _req(etiqueta: str, valor: Any, opcional: bool = False) -> tuple[str, bool, bool]:
    return (etiqueta, bool(valor), opcional)


def _req_catalogo() -> list[tuple[str, bool, bool]]:
    return [_req("data/productos.yaml", config.PRODUCTOS_YAML.exists())]


def _req_presupuestos() -> list[tuple[str, bool, bool]]:
    return [
        _req("EMPRESA_CUIT", config.EMPRESA_CUIT, opcional=True),
        _req("PRESUPUESTOS_BASE_URL (link público)", config.PRESUPUESTOS_BASE_URL, opcional=True),
    ]


def _req_calendar() -> list[tuple[str, bool, bool]]:
    return [
        _req("GOOGLE_CALENDAR_CLIENT_ID", config.GOOGLE_CALENDAR_CLIENT_ID),
        _req("GOOGLE_CALENDAR_CLIENT_SECRET", config.GOOGLE_CALENDAR_CLIENT_SECRET),
        _req("GOOGLE_CALENDAR_REFRESH_TOKEN", config.GOOGLE_CALENDAR_REFRESH_TOKEN),
    ]


def _req_kommo() -> list[tuple[str, bool, bool]]:
    return [
        _req("KOMMO_SUBDOMAIN", config.KOMMO_SUBDOMAIN),
        _req("KOMMO_ACCESS_TOKEN", config.KOMMO_ACCESS_TOKEN),
        _req("KOMMO_PIPELINE_ID", config.KOMMO_PIPELINE_ID, opcional=True),
        _req("KOMMO_STATUS_*_ID (mapeo de etapas)", config.KOMMO_STATUS_MEDIA_ID, opcional=True),
        _req("KOMMO_RESPONSABLE_DEFAULT_ID", config.KOMMO_RESPONSABLE_DEFAULT_ID, opcional=True),
    ]


GRUPOS: list[dict[str, Any]] = [
    {
        "clave": "catalogo",
        "nombre": "Catálogo y productos",
        "descripcion": "Consultar productos, FAQs y precios desde productos.yaml.",
        "requisitos": _req_catalogo,
    },
    {
        "clave": "validacion",
        "nombre": "Validación",
        "descripcion": "Validación de CUIT/CUIL con el algoritmo de AFIP.",
        "requisitos": lambda: [],
    },
    {
        "clave": "leads",
        "nombre": "Leads (base local)",
        "descripcion": "Alta, clasificación y consulta de leads en la base SQLite local.",
        "requisitos": lambda: [],
    },
    {
        "clave": "presupuestos",
        "nombre": "Presupuestos (PDF)",
        "descripcion": "Generación del PDF de presupuesto y marcado del lead como ALTA.",
        "requisitos": _req_presupuestos,
    },
    {
        "clave": "calendar",
        "nombre": "Agenda (Google Calendar)",
        "descripcion": "Crear reuniones reales con link de Google Meet para el lead.",
        "requisitos": _req_calendar,
    },
    {
        "clave": "kommo",
        "nombre": "Kommo CRM",
        "descripcion": "Sincronizar leads, notas y tareas con el CRM Kommo.",
        "requisitos": _req_kommo,
    },
    {
        "clave": "utilitarias",
        "nombre": "Utilitarias",
        "descripcion": "System prompt para n8n/GPT y recarga del catálogo.",
        "requisitos": lambda: [],
    },
    {
        "clave": "otras",
        "nombre": "Otras",
        "descripcion": "Tools registradas sin grupo asignado.",
        "requisitos": lambda: [],
    },
]

# Mapeo nombre de tool -> clave de grupo.
TOOL_GRUPO: dict[str, str] = {
    # catálogo
    "productos_disponibles": "catalogo",
    "info_producto": "catalogo",
    "faqs_producto": "catalogo",
    "identificar_producto_interes": "catalogo",
    # validación
    "validar_cuit": "validacion",
    # leads
    "registrar_lead": "leads",
    "clasificar_lead": "leads",
    "buscar_lead": "leads",
    "listar_leads": "leads",
    # presupuestos
    "generar_presupuesto": "presupuestos",
    # calendar
    "agendar_reunion": "calendar",
    # kommo
    "kommo_listar_pipelines": "kommo",
    "kommo_listar_usuarios": "kommo",
    "kommo_buscar_lead": "kommo",
    "kommo_obtener_lead": "kommo",
    "kommo_crear_lead": "kommo",
    "kommo_actualizar_lead": "kommo",
    "kommo_mover_lead": "kommo",
    "kommo_asignar_responsable": "kommo",
    "kommo_agregar_nota": "kommo",
    "kommo_crear_tarea": "kommo",
    # utilitarias
    "prompt_sistema": "utilitarias",
    "recargar_catalogo": "utilitarias",
}


def grupo_de(tool_name: str) -> str:
    return TOOL_GRUPO.get(tool_name, "otras")


def estado_grupo(requisitos: Callable[[], list[tuple[str, bool, bool]]]) -> dict[str, Any]:
    """Resuelve el estado de configuración de un grupo a partir de sus requisitos."""
    reqs = requisitos()
    obligatorios = [r for r in reqs if not r[2]]
    faltan_oblig = [r for r in obligatorios if not r[1]]
    if not reqs:
        estado = "siempre"  # no necesita configuración
    elif not obligatorios:
        estado = "opcional"  # solo tiene ajustes opcionales
    elif faltan_oblig:
        estado = "falta"
    else:
        estado = "ok"
    return {"estado": estado, "requisitos": reqs}


def extraer_parametros(parameters: dict[str, Any]) -> list[dict[str, Any]]:
    """Aplana el JSON-Schema de una tool a una lista de parámetros legibles.

    Las tools envuelven sus campos en un objeto ``datos``; si existe, se
    desanida. Devuelve [{nombre, tipo, requerido, descripcion}, ...].
    """
    props = parameters.get("properties", {}) or {}
    requeridos = set(parameters.get("required", []) or [])

    # Desanidar el envoltorio `datos` (modelo Pydantic de la firma).
    if set(props.keys()) == {"datos"} and isinstance(props["datos"], dict):
        datos = props["datos"]
        props = datos.get("properties", {}) or {}
        requeridos = set(datos.get("required", []) or [])

    out: list[dict[str, Any]] = []
    for nombre, esquema in props.items():
        out.append(
            {
                "nombre": nombre,
                "tipo": _tipo_legible(esquema),
                "requerido": nombre in requeridos,
                "descripcion": esquema.get("description", ""),
            }
        )
    return out


def _tipo_legible(esquema: dict[str, Any]) -> str:
    if "type" in esquema:
        return str(esquema["type"])
    # anyOf [tipo, null] -> tipo (opcional)
    if "anyOf" in esquema:
        tipos = [s.get("type") for s in esquema["anyOf"] if s.get("type") and s.get("type") != "null"]
        if tipos:
            return "/".join(tipos)
    return "any"
