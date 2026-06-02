"""
MCP server de Consultoría Digital.

Exposición:
    - Transporte HTTP (streamable-http) en MCP_HOST:MCP_PORT, path /mcp/
    - Bearer auth opcional vía MCP_AUTH_TOKEN

Para conectarlo desde n8n, usar el nodo `MCP Client` con:
    URL:      http://VPS_IP:PORT/mcp/
    Header:   Authorization: Bearer <MCP_AUTH_TOKEN>

NOTA importante: el MCP Client de n8n inyecta campos del flujo (text, num,
toolCallId, ...) al MISMO nivel que `datos` en el `params.arguments` de cada
`tools/call`. Manejo en dos capas:
- Los modelos heredan de `LooseModel` (extra='ignore'): absorbe extras
  metidos DENTRO de `datos`.
- Una middleware ASGI (`StripN8nEnvelopeMiddleware`) limpia los campos
  conocidos del envelope ANTES de que el JSON-RPC llegue a FastMCP, porque
  FastMCP no permite `**kwargs` en la firma de las tools.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import uuid4

import uvicorn
from fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Mount

from src import (
    admin,
    calendar_google,
    catalogo,
    config,
    cuit as cuit_mod,
    kommo,
    leads,
    pdf as pdf_mod,
)
from src.db import init_db
from src.prompts import SYSTEM_PROMPT

# ---------------------------------------------------------------------------
# Inicialización
# ---------------------------------------------------------------------------
init_db()
mcp = FastMCP(name="Consultoria Digital MCP")


class LooseModel(BaseModel):
    """Modelo base que ignora cualquier campo extra que mande el cliente."""

    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Tools: productos / FAQs
# ---------------------------------------------------------------------------

class ProductoKeyInput(LooseModel):
    producto: str = Field(..., description="Clave del producto: gestion_redes, pauta_meta, crm, concilia, turneria.")


class TextoClienteInput(LooseModel):
    texto_cliente: str = Field(..., description="Texto enviado por el lead, para inferir producto de interés.")


@mcp.tool
def productos_disponibles() -> dict[str, Any]:
    """Lista los productos que comercializa Consultoría Digital, con claves y nombres comerciales."""
    return {
        "productos": [
            {"clave": k, "nombre": v.get("nombre"), "descripcion": v.get("descripcion")}
            for k, v in catalogo.productos().items()
        ],
        "criterios_cliente": catalogo.cargar().get("criterios_cliente", []),
    }


@mcp.tool
def info_producto(datos: ProductoKeyInput) -> dict[str, Any]:
    """Información detallada de un producto: nombre, descripción, qué incluye y precio desde."""
    p = catalogo.producto(datos.producto)
    if not p:
        return {"error": f"Producto '{datos.producto}' no encontrado", "claves_validas": catalogo.claves_productos()}
    return {
        "clave": datos.producto,
        "nombre": p.get("nombre"),
        "descripcion": p.get("descripcion"),
        "incluye": p.get("incluye", []),
        "precio_desde": p.get("precio_desde"),
        "precio_moneda": p.get("precio_moneda"),
        "precio_unidad": p.get("precio_unidad"),
    }


@mcp.tool
def faqs_producto(datos: ProductoKeyInput) -> dict[str, Any]:
    """Devuelve las preguntas frecuentes y respuestas oficiales de un producto."""
    p = catalogo.producto(datos.producto)
    if not p:
        return {"error": f"Producto '{datos.producto}' no encontrado"}
    return {"producto": datos.producto, "faqs": p.get("faqs", [])}


@mcp.tool
def identificar_producto_interes(datos: TextoClienteInput) -> dict[str, Any]:
    """Analiza el mensaje del lead y sugiere qué producto le interesa, en base a keywords del catálogo."""
    matches = catalogo.identificar_por_texto(datos.texto_cliente)
    return {
        "matches": [
            {"clave": c, "nombre": catalogo.producto(c).get("nombre"), "score": s}
            for c, s in matches
        ],
        "sugerencia": matches[0][0] if matches else None,
    }


# ---------------------------------------------------------------------------
# Tools: CUIT
# ---------------------------------------------------------------------------

class CuitInput(LooseModel):
    cuit: str = Field(..., description="CUIT en cualquier formato (con o sin guiones).")


@mcp.tool
def validar_cuit(datos: CuitInput) -> dict[str, Any]:
    """Valida un CUIT argentino (11 dígitos + verificador). Devuelve si es válido y el formato canónico."""
    return {
        "cuit_ingresado": datos.cuit,
        "cuit_normalizado": cuit_mod.normalizar(datos.cuit),
        "valido": cuit_mod.es_valido(datos.cuit),
        "formateado": cuit_mod.formatear(datos.cuit),
    }


# ---------------------------------------------------------------------------
# Tools: leads (estado local en SQLite)
# ---------------------------------------------------------------------------

class RegistrarLeadInput(LooseModel):
    telefono: str | None = Field(None, description="Teléfono / wa_id del lead (clave de upsert).")
    nombre: str | None = None
    empresa: str | None = None
    cuit: str | None = None
    producto_interes: str | None = Field(
        None, description="Clave del producto: gestion_redes, pauta_meta, crm, concilia, turneria"
    )
    clasificacion: str | None = Field(
        None,
        description="INICIAL | PRODUCTO_IDENTIFICADO | MEDIA | ALTA | DESCARTADO.",
    )
    notas: str | None = None
    mensaje: str | None = Field(
        None,
        description="Opcional: último mensaje del cliente a guardar en el historial de chat junto con el registro.",
    )


@mcp.tool
def registrar_lead(datos: RegistrarLeadInput) -> dict[str, Any]:
    """Crea o actualiza un lead (upsert por teléfono). Llamala después de cada turno relevante."""
    if datos.clasificacion and datos.clasificacion not in leads.VALIDAS:
        return {"error": f"clasificacion inválida: {datos.clasificacion}", "validas": sorted(leads.VALIDAS)}
    if datos.producto_interes and datos.producto_interes not in catalogo.claves_productos():
        return {"error": f"producto_interes inválido: {datos.producto_interes}", "validos": catalogo.claves_productos()}
    campos = datos.model_dump()
    mensaje = campos.pop("mensaje", None)
    lead = leads.upsert(**campos)
    leads.registrar_evento(lead["id"], "registrar_lead", f"clasificacion={lead['clasificacion']}")
    if mensaje:
        leads.guardar_mensaje(lead["id"], "cliente", mensaje)
    return {"lead": lead}


class ClasificarLeadInput(LooseModel):
    lead_id: int
    clasificacion: str = Field(..., description="INICIAL | PRODUCTO_IDENTIFICADO | MEDIA | ALTA | DESCARTADO.")
    motivo: str | None = None


@mcp.tool
def clasificar_lead(datos: ClasificarLeadInput) -> dict[str, Any]:
    """Cambia la clasificación de un lead local y deja registro del motivo."""
    if datos.clasificacion not in leads.VALIDAS:
        return {"error": "clasificacion inválida", "validas": sorted(leads.VALIDAS)}
    actual = leads.obtener(datos.lead_id)
    if not actual:
        return {"error": f"lead {datos.lead_id} no encontrado"}
    lead = leads.upsert(telefono=actual["telefono"], clasificacion=datos.clasificacion)
    leads.registrar_evento(
        lead["id"], "clasificar",
        f"{actual['clasificacion']}→{datos.clasificacion}: {datos.motivo or ''}",
    )
    return {"lead": lead}


class TelefonoInput(LooseModel):
    telefono: str = Field(..., description="Teléfono / wa_id del lead.")


@mcp.tool
def buscar_lead(datos: TelefonoInput) -> dict[str, Any]:
    """Busca un lead por teléfono. Útil para que el agente recupere el estado al inicio del turno."""
    lead = leads.buscar_por_telefono(datos.telefono)
    return {"lead": lead}


class ListarLeadsInput(LooseModel):
    clasificacion: str | None = None
    limit: int = 50


@mcp.tool
def listar_leads(datos: ListarLeadsInput) -> dict[str, Any]:
    """Lista los últimos leads, opcionalmente filtrando por clasificación. Uso interno."""
    return {"leads": leads.listar(clasificacion=datos.clasificacion, limit=datos.limit)}


class GuardarMensajeInput(LooseModel):
    telefono: str = Field(..., description="Teléfono / wa_id del lead (se crea el lead si no existe).")
    texto: str = Field(..., description="Contenido del mensaje a guardar en el historial de chat.")
    rol: str = Field(
        "cliente",
        description="Quién escribió: 'cliente' (el lead), 'asistente' (el bot) o 'sistema'.",
    )


@mcp.tool
def guardar_mensaje(datos: GuardarMensajeInput) -> dict[str, Any]:
    """Guarda un mensaje del chat en el historial del lead. Llamala en cada turno (cliente y asistente).

    Si el teléfono no existe todavía, crea el lead automáticamente (clasificación INICIAL).
    """
    rol = datos.rol.lower().strip()
    if rol not in leads.ROLES_MENSAJE:
        return {"error": f"rol inválido: {datos.rol}", "validos": sorted(leads.ROLES_MENSAJE)}
    lead = leads.buscar_por_telefono(datos.telefono) or leads.upsert(telefono=datos.telefono)
    mensaje_id = leads.guardar_mensaje(lead["id"], rol, datos.texto)
    return {"mensaje_id": mensaje_id, "lead_id": lead["id"]}


@mcp.tool
def estado_por_telefono(datos: TelefonoInput) -> dict[str, Any]:
    """Estado COMPLETO de un lead por teléfono en un solo llamado: datos del lead +
    historial de chat (mensajes) + eventos + presupuestos. Usala al inicio del turno
    para recuperar todo el contexto y ver en qué producto está interesado.
    """
    estado = leads.estado_completo(datos.telefono)
    if not estado:
        return {"lead": None, "encontrado": False}
    return {"encontrado": True, **estado}


# ---------------------------------------------------------------------------
# Tools: presupuesto
# ---------------------------------------------------------------------------

class ItemPresupuesto(LooseModel):
    descripcion: str
    cantidad: float = 1
    precio_unitario: float


class GenerarPresupuestoInput(LooseModel):
    lead_id: int = Field(..., description="ID del lead local al que se le emite el presupuesto.")
    producto: str = Field(..., description="Clave del producto (gestion_redes, pauta_meta, etc.).")
    items: list[ItemPresupuesto] = Field(..., min_length=1)
    notas: str | None = None
    validez_dias: int | None = None


@mcp.tool
def generar_presupuesto(datos: GenerarPresupuestoInput) -> dict[str, Any]:
    """Genera el PDF de presupuesto para un lead. Requisitos: empresa + CUIT cargados. Marca al lead como ALTA."""
    p = catalogo.producto(datos.producto)
    if not p:
        return {"error": f"Producto '{datos.producto}' no encontrado"}

    lead = leads.obtener(datos.lead_id)
    if not lead:
        return {"error": f"Lead {datos.lead_id} no encontrado"}
    if not lead.get("empresa") or not lead.get("cuit"):
        return {"error": "El lead no tiene empresa o CUIT cargados. Pedirlos antes de cotizar.", "lead": lead}
    if not cuit_mod.es_valido(lead["cuit"]):
        return {"error": f"CUIT inválido en el lead: {lead['cuit']}"}

    numero = f"CD-{datetime.now().strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}"
    archivo = config.PRESUPUESTOS_DIR / f"{numero}.pdf"

    items = [
        pdf_mod.Item(descripcion=it.descripcion, cantidad=it.cantidad, precio_unitario=it.precio_unitario)
        for it in datos.items
    ]
    total = sum(it.subtotal for it in items)

    pdf_mod.generar_presupuesto(
        archivo=archivo,
        numero=numero,
        cliente_empresa=lead["empresa"],
        cliente_cuit=cuit_mod.formatear(lead["cuit"]),
        cliente_contacto=lead.get("nombre"),
        producto_nombre=p.get("nombre", datos.producto),
        items=items,
        notas=datos.notas,
        validez_dias=datos.validez_dias,
    )

    url_publica = (
        f"{config.PRESUPUESTOS_BASE_URL}/{archivo.name}"
        if config.PRESUPUESTOS_BASE_URL
        else None
    )

    presupuesto_id = leads.guardar_presupuesto(
        lead_id=lead["id"],
        producto=datos.producto,
        archivo=str(archivo),
        url_publica=url_publica,
        total_ars=total,
    )
    lead = leads.upsert(telefono=lead["telefono"], clasificacion="ALTA")
    leads.registrar_evento(
        lead["id"], "presupuesto_enviado", f"#{numero} total={total} producto={datos.producto}"
    )

    return {
        "presupuesto_id": presupuesto_id,
        "numero": numero,
        "archivo": str(archivo),
        "url_publica": url_publica,
        "total_ars": total,
        "lead": lead,
    }


# ---------------------------------------------------------------------------
# Tools: agendar reunión (Google Calendar)
# ---------------------------------------------------------------------------

class AgendarReunionInput(LooseModel):
    lead_id: int = Field(..., description="ID del lead local con quien se agenda la reunión.")
    fecha_hora_iso: str = Field(
        ...,
        description=(
            "ISO 8601 en hora local Argentina, ej '2026-05-25T15:00:00'. "
            "Sin offset — se asume el GOOGLE_CALENDAR_TIMEZONE del .env."
        ),
    )
    duracion_min: int | None = Field(
        None,
        description="Duración en minutos. Default 30 (GOOGLE_CALENDAR_DURACION_DEFAULT_MIN).",
    )
    titulo: str | None = Field(
        None,
        description="Título del evento. Default: 'Reunión Consultoría Digital — <empresa o nombre>'.",
    )
    notas: str | None = Field(None, description="Descripción / agenda interna del evento.")
    invitar_email: str | None = Field(
        None,
        description="Email del lead a invitar. Si se pasa, Google manda invite y agrega al Meet.",
    )


@mcp.tool
def agendar_reunion(datos: AgendarReunionInput) -> dict[str, Any]:
    """Crea una reunión real en Google Calendar (con link de Meet) para el lead.

    Devuelve `event_id`, `html_link` (vista del evento), `meet_link` (Google Meet),
    `inicio`, `fin` y `timezone`. Si faltan credenciales o falla la API devuelve
    `{"error": "..."}`. El lead debe existir previamente.
    """
    lead = leads.obtener(datos.lead_id)
    if not lead:
        return {"error": f"Lead {datos.lead_id} no encontrado"}

    titulo = datos.titulo or (
        f"Reunión Consultoría Digital — {lead.get('empresa') or lead.get('nombre') or 'Lead'}"
    )
    descripcion = datos.notas or (
        f"Reunión con lead #{lead['id']}"
        f" ({lead.get('telefono') or 'sin teléfono'}, "
        f"{lead.get('empresa') or 'sin empresa'})"
    )
    invitados = [datos.invitar_email] if datos.invitar_email else []

    try:
        evento = calendar_google.crear_evento(
            titulo=titulo,
            descripcion=descripcion,
            inicio_iso=datos.fecha_hora_iso,
            duracion_min=datos.duracion_min or config.GOOGLE_CALENDAR_DURACION_DEFAULT_MIN,
            invitados_emails=invitados,
        )
    except calendar_google.CalendarError as e:
        return {"error": str(e), "status": e.status, "body": e.body}

    leads.registrar_evento(
        lead["id"],
        "reunion_agendada",
        f"{evento['inicio']} → {evento.get('meet_link') or evento.get('html_link')}",
    )
    return evento


# ---------------------------------------------------------------------------
# Tools: Kommo CRM
# ---------------------------------------------------------------------------

_CLASIF_A_STATUS_ENV = {
    "INICIAL": "KOMMO_STATUS_INICIAL_ID",
    "PRODUCTO_IDENTIFICADO": "KOMMO_STATUS_INICIAL_ID",
    "MEDIA": "KOMMO_STATUS_MEDIA_ID",
    "ALTA": "KOMMO_STATUS_ALTA_ID",
    "DESCARTADO": "KOMMO_STATUS_DESCARTADO_ID",
}


def _status_id_para_clasificacion(clasificacion: str) -> int | None:
    attr = _CLASIF_A_STATUS_ENV.get(clasificacion)
    return getattr(config, attr) if attr else None


def _kommo_safe(fn, *args, **kwargs) -> dict[str, Any]:
    try:
        result = fn(*args, **kwargs)
    except kommo.KommoError as e:
        return {"error": str(e), "status": e.status, "body": e.body}
    return {"ok": True, "data": result}


@mcp.tool
def kommo_listar_pipelines() -> dict[str, Any]:
    """Lista pipelines de Kommo con sus statuses anidados (para descubrir IDs)."""
    return _kommo_safe(kommo.listar_pipelines)


@mcp.tool
def kommo_listar_usuarios() -> dict[str, Any]:
    """Lista usuarios de Kommo con sus IDs (para asignar como responsables)."""
    return _kommo_safe(kommo.listar_usuarios)


class KommoBuscarLeadInput(LooseModel):
    query: str = Field(..., description="Texto libre: nombre, teléfono o email del lead.")
    limit: int = 10


@mcp.tool
def kommo_buscar_lead(datos: KommoBuscarLeadInput) -> dict[str, Any]:
    """Busca leads en Kommo por texto libre. Útil para chequear si un lead ya existe antes de crearlo."""
    return _kommo_safe(kommo.buscar_leads, datos.query, datos.limit)


class KommoLeadIdInput(LooseModel):
    lead_id: int


@mcp.tool
def kommo_obtener_lead(datos: KommoLeadIdInput) -> dict[str, Any]:
    """Devuelve un lead de Kommo por ID, con sus contactos asociados."""
    return _kommo_safe(kommo.obtener_lead, datos.lead_id)


class KommoCrearLeadInput(LooseModel):
    name: str = Field(..., description="Nombre del lead (ej: 'Pauta Meta - Juan Pérez').")
    contacto_nombre: str | None = None
    contacto_telefono: str | None = Field(None, description="Teléfono en formato internacional, ej +5491155551234.")
    contacto_email: str | None = None
    empresa_nombre: str | None = None
    pipeline_id: int | None = Field(None, description="Si se omite, usa KOMMO_PIPELINE_ID del .env.")
    status_id: int | None = None
    responsible_user_id: int | None = Field(None, description="Si se omite, usa KOMMO_RESPONSABLE_DEFAULT_ID del .env.")
    price: int | None = None
    tags: list[str] | None = None


@mcp.tool
def kommo_crear_lead(datos: KommoCrearLeadInput) -> dict[str, Any]:
    """Crea un lead en Kommo (con contacto y opcionalmente compañía) en una sola operación."""
    payload = datos.model_dump()
    payload["pipeline_id"] = payload.get("pipeline_id") or config.KOMMO_PIPELINE_ID
    payload["responsible_user_id"] = (
        payload.get("responsible_user_id") or config.KOMMO_RESPONSABLE_DEFAULT_ID
    )
    return _kommo_safe(kommo.crear_lead_complejo, **payload)


class KommoActualizarLeadInput(LooseModel):
    lead_id: int
    name: str | None = None
    pipeline_id: int | None = None
    status_id: int | None = None
    responsible_user_id: int | None = None
    price: int | None = None


@mcp.tool
def kommo_actualizar_lead(datos: KommoActualizarLeadInput) -> dict[str, Any]:
    """Actualiza campos puntuales de un lead en Kommo (nombre, pipeline, status, responsable, precio)."""
    return _kommo_safe(
        kommo.actualizar_lead,
        datos.lead_id,
        name=datos.name,
        pipeline_id=datos.pipeline_id,
        status_id=datos.status_id,
        responsible_user_id=datos.responsible_user_id,
        price=datos.price,
    )


class KommoMoverLeadInput(LooseModel):
    lead_id: int
    status_id: int | None = None
    clasificacion: str | None = Field(
        None, description="INICIAL | MEDIA | ALTA | DESCARTADO (resuelve status_id desde el .env)."
    )
    pipeline_id: int | None = None


@mcp.tool
def kommo_mover_lead(datos: KommoMoverLeadInput) -> dict[str, Any]:
    """Mueve un lead a otro estado en Kommo. Aceptá `status_id` directo o `clasificacion` (mapea desde .env)."""
    status_id = datos.status_id
    if status_id is None and datos.clasificacion:
        status_id = _status_id_para_clasificacion(datos.clasificacion.upper())
        if status_id is None:
            return {"error": f"No hay KOMMO_STATUS_*_ID configurado para clasificacion '{datos.clasificacion}'."}
    if status_id is None:
        return {"error": "Debe pasarse status_id o clasificacion."}
    return _kommo_safe(
        kommo.actualizar_lead,
        datos.lead_id,
        status_id=status_id,
        pipeline_id=datos.pipeline_id or config.KOMMO_PIPELINE_ID,
    )


class KommoAsignarResponsableInput(LooseModel):
    lead_id: int
    responsible_user_id: int


@mcp.tool
def kommo_asignar_responsable(datos: KommoAsignarResponsableInput) -> dict[str, Any]:
    """Asigna o cambia el usuario responsable de un lead en Kommo."""
    return _kommo_safe(
        kommo.actualizar_lead, datos.lead_id, responsible_user_id=datos.responsible_user_id
    )


class KommoAgregarNotaInput(LooseModel):
    lead_id: int
    texto: str


@mcp.tool
def kommo_agregar_nota(datos: KommoAgregarNotaInput) -> dict[str, Any]:
    """Agrega una nota al historial del lead en Kommo (trazabilidad de la conversación)."""
    return _kommo_safe(kommo.agregar_nota, datos.lead_id, datos.texto)


class KommoCrearTareaInput(LooseModel):
    lead_id: int
    texto: str = Field(..., description="Descripción de la tarea, ej 'Llamar para coordinar reunión'.")
    vencimiento_unix: int = Field(..., description="Timestamp UNIX (segundos) de vencimiento.")
    responsible_user_id: int | None = None
    task_type_id: int | None = Field(None, description="1=Follow-up, 2=Call, 3=Meeting (defaults Kommo).")


@mcp.tool
def kommo_crear_tarea(datos: KommoCrearTareaInput) -> dict[str, Any]:
    """Crea una tarea asociada a un lead en Kommo (recordatorio para el comercial)."""
    return _kommo_safe(
        kommo.crear_tarea,
        lead_id=datos.lead_id,
        texto=datos.texto,
        complete_till_unix=datos.vencimiento_unix,
        responsible_user_id=datos.responsible_user_id or config.KOMMO_RESPONSABLE_DEFAULT_ID,
        task_type_id=datos.task_type_id,
    )


# ---------------------------------------------------------------------------
# Tools: utilitarias
# ---------------------------------------------------------------------------

@mcp.tool
def prompt_sistema() -> dict[str, str]:
    """Devuelve el system prompt sugerido para configurar al agente comercial en n8n/GPT."""
    return {"system_prompt": SYSTEM_PROMPT}


@mcp.tool
def recargar_catalogo() -> dict[str, Any]:
    """Recarga el catálogo de productos desde productos.yaml sin reiniciar el server."""
    data = catalogo.recargar()
    return {"productos_cargados": list(data.get("productos", {}).keys())}


# ---------------------------------------------------------------------------
# Bearer auth (opcional) y arranque
# ---------------------------------------------------------------------------

class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Bearer auth SOLO para el MCP (/mcp). El panel /admin usa su propia sesión."""

    async def dispatch(self, request, call_next):  # type: ignore[override]
        if not request.url.path.startswith("/mcp") or not config.MCP_AUTH_TOKEN:
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        expected = f"Bearer {config.MCP_AUTH_TOKEN}"
        if auth != expected:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


# Campos que el MCP Client de n8n inyecta dentro de `params.arguments` en cada
# `tools/call` y que FastMCP rechaza como kwargs inesperados contra la firma
# de la tool. Ver docstring del módulo.
N8N_ENVELOPE_FIELDS = frozenset({"text", "num", "toolCallId"})


class StripN8nEnvelopeMiddleware:
    """ASGI middleware que limpia el envelope de n8n del JSON-RPC entrante.

    Para cada request POST con body JSON-RPC que tenga `method == "tools/call"`,
    elimina del dict `params.arguments` los campos en `N8N_ENVELOPE_FIELDS`.
    Si el body no parsea como JSON o no contiene una llamada de tool, se
    reenvía sin modificar.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return

        # Buffer del body completo
        chunks: list[bytes] = []
        more_body = True
        while more_body:
            message = await receive()
            chunks.append(message.get("body", b""))
            more_body = message.get("more_body", False)
        body = b"".join(chunks)

        # Intento de strip — silencioso ante cualquier error
        new_body = body
        try:
            payload = json.loads(body)
            items = payload if isinstance(payload, list) else [payload]
            modified = False
            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("method") != "tools/call":
                    continue
                args = item.get("params", {}).get("arguments")
                if not isinstance(args, dict):
                    continue
                for k in list(args.keys()):
                    if k in N8N_ENVELOPE_FIELDS:
                        args.pop(k)
                        modified = True
            if modified:
                new_body = json.dumps(payload).encode("utf-8")
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            pass

        # Actualizar Content-Length si cambió el body
        if new_body is not body:
            new_headers = [
                (name, value)
                for name, value in scope.get("headers", [])
                if name.lower() != b"content-length"
            ]
            new_headers.append((b"content-length", str(len(new_body)).encode()))
            scope = {**scope, "headers": new_headers}

        # Replay del body: la primera llamada devuelve el body (posiblemente
        # modificado), las siguientes delegan al receive original para no
        # romper streams (SSE / long-poll) donde la app sigue escuchando.
        body_sent = False

        async def wrapped_receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": new_body, "more_body": False}
            return await receive()

        await self.app(scope, wrapped_receive, send)


def build_app() -> Starlette:
    mcp_app = mcp.http_app(path="/mcp")
    wrapped_mcp = StripN8nEnvelopeMiddleware(mcp_app)
    return Starlette(
        routes=[
            # Panel de administración (sesión propia por contraseña).
            *admin.routes(),
            # Catch-all: MCP server (bearer auth) montado en /mcp.
            Mount("/", app=wrapped_mcp),
        ],
        middleware=[Middleware(BearerAuthMiddleware)],
        lifespan=mcp_app.lifespan,
    )


app = build_app()


if __name__ == "__main__":
    uvicorn.run(app, host=config.MCP_HOST, port=config.MCP_PORT)
