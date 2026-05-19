"""
MCP server de Consultoría Digital.

Exposición:
    - Transporte HTTP (streamable-http) en MCP_HOST:MCP_PORT, path /mcp/
    - Bearer auth opcional vía MCP_AUTH_TOKEN

Para conectarlo desde n8n, usar el nodo `MCP Client` con:
    URL:      http://VPS_IP:PORT/mcp/
    Header:   Authorization: Bearer <MCP_AUTH_TOKEN>
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import uvicorn
from fastmcp import FastMCP
from pydantic import BaseModel, Field
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Mount

from src import catalogo, config, cuit as cuit_mod, kommo, leads, pdf as pdf_mod
from src.db import init_db
from src.prompts import SYSTEM_PROMPT

# ---------------------------------------------------------------------------
# Inicialización
# ---------------------------------------------------------------------------
init_db()
mcp = FastMCP(name="Consultoria Digital MCP")


# ---------------------------------------------------------------------------
# Tools: productos / FAQs
# ---------------------------------------------------------------------------

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
def info_producto(producto: str) -> dict[str, Any]:
    """
    Devuelve la información detallada de un producto: nombre, descripción,
    qué incluye y rango de precio (si está cargado).

    Args:
        producto: clave del producto (ej. 'gestion_redes', 'pauta_meta',
                  'crm', 'concilia', 'turneria').
    """
    p = catalogo.producto(producto)
    if not p:
        return {"error": f"Producto '{producto}' no encontrado", "claves_validas": catalogo.claves_productos()}
    return {
        "clave": producto,
        "nombre": p.get("nombre"),
        "descripcion": p.get("descripcion"),
        "incluye": p.get("incluye", []),
        "precio_desde": p.get("precio_desde"),
        "precio_moneda": p.get("precio_moneda"),
        "precio_unidad": p.get("precio_unidad"),
    }


@mcp.tool
def faqs_producto(producto: str) -> dict[str, Any]:
    """Devuelve las preguntas frecuentes y respuestas oficiales de un producto."""
    p = catalogo.producto(producto)
    if not p:
        return {"error": f"Producto '{producto}' no encontrado"}
    return {"producto": producto, "faqs": p.get("faqs", [])}


@mcp.tool
def identificar_producto_interes(texto_cliente: str) -> dict[str, Any]:
    """
    Analiza el mensaje del lead y sugiere qué producto le interesa, en base a
    keywords del catálogo. Devuelve una lista ordenada por score.
    """
    matches = catalogo.identificar_por_texto(texto_cliente)
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

@mcp.tool
def validar_cuit(cuit: str) -> dict[str, Any]:
    """Valida un CUIT argentino (11 dígitos + verificador). Devuelve si es válido y el formato canónico."""
    return {
        "cuit_ingresado": cuit,
        "cuit_normalizado": cuit_mod.normalizar(cuit),
        "valido": cuit_mod.es_valido(cuit),
        "formateado": cuit_mod.formatear(cuit),
    }


# ---------------------------------------------------------------------------
# Tools: leads
# ---------------------------------------------------------------------------

class RegistrarLeadInput(BaseModel):
    telefono: str | None = Field(None, description="Teléfono / wa_id del lead (clave de upsert).")
    nombre: str | None = None
    empresa: str | None = None
    cuit: str | None = None
    producto_interes: str | None = Field(
        None, description="Clave del producto: gestion_redes, pauta_meta, crm, concilia, turneria"
    )
    clasificacion: str | None = Field(
        None,
        description="INICIAL | PRODUCTO_IDENTIFICADO | MEDIA | ALTA | DESCARTADO. "
                    "Si se omite, mantiene la actual o setea INICIAL.",
    )
    notas: str | None = None


@mcp.tool
def registrar_lead(datos: RegistrarLeadInput) -> dict[str, Any]:
    """
    Crea o actualiza un lead. La clave de upsert es el teléfono.

    Llamala después de cada turno relevante de conversación para mantener
    actualizado nombre, empresa, CUIT, producto de interés y clasificación.
    """
    if datos.clasificacion and datos.clasificacion not in leads.VALIDAS:
        return {
            "error": f"clasificacion inválida: {datos.clasificacion}",
            "validas": sorted(leads.VALIDAS),
        }
    if datos.producto_interes and datos.producto_interes not in catalogo.claves_productos():
        return {
            "error": f"producto_interes inválido: {datos.producto_interes}",
            "validos": catalogo.claves_productos(),
        }
    lead = leads.upsert(**datos.model_dump())
    leads.registrar_evento(lead["id"], "registrar_lead", f"clasificacion={lead['clasificacion']}")
    return {"lead": lead}


@mcp.tool
def clasificar_lead(lead_id: int, clasificacion: str, motivo: str | None = None) -> dict[str, Any]:
    """
    Cambia la clasificación de un lead y deja registro del motivo.

    Clasificaciones:
      - INICIAL: recién llegado.
      - PRODUCTO_IDENTIFICADO: ya sabemos qué producto le interesa.
      - MEDIA: entregó CUIT válido + nombre de empresa.
      - ALTA: ya se le envió presupuesto y se propuso reunión.
      - DESCARTADO: no cumple criterios (sin CUIT activo, fuera de alcance, etc.).
    """
    if clasificacion not in leads.VALIDAS:
        return {"error": f"clasificacion inválida", "validas": sorted(leads.VALIDAS)}
    actual = leads.obtener(lead_id)
    if not actual:
        return {"error": f"lead {lead_id} no encontrado"}
    lead = leads.upsert(telefono=actual["telefono"], clasificacion=clasificacion)
    leads.registrar_evento(lead["id"], "clasificar", f"{actual['clasificacion']}→{clasificacion}: {motivo or ''}")
    return {"lead": lead}


@mcp.tool
def buscar_lead(telefono: str) -> dict[str, Any]:
    """Busca un lead por teléfono. Útil para que el agente recupere el estado al inicio del turno."""
    lead = leads.buscar_por_telefono(telefono)
    return {"lead": lead}


@mcp.tool
def listar_leads(clasificacion: str | None = None, limit: int = 50) -> dict[str, Any]:
    """Lista los últimos leads, opcionalmente filtrando por clasificación. Pensado para uso interno."""
    return {"leads": leads.listar(clasificacion=clasificacion, limit=limit)}


# ---------------------------------------------------------------------------
# Tools: presupuesto
# ---------------------------------------------------------------------------

class ItemPresupuesto(BaseModel):
    descripcion: str
    cantidad: float = 1
    precio_unitario: float


class GenerarPresupuestoInput(BaseModel):
    lead_id: int = Field(..., description="ID del lead al que se le emite el presupuesto.")
    producto: str = Field(..., description="Clave del producto (gestion_redes, pauta_meta, etc.).")
    items: list[ItemPresupuesto] = Field(..., min_length=1)
    notas: str | None = None
    validez_dias: int | None = None


@mcp.tool
def generar_presupuesto(datos: GenerarPresupuestoInput) -> dict[str, Any]:
    """
    Genera el PDF de presupuesto para un lead.

    Requisitos previos: el lead debe tener empresa y CUIT cargados.
    Devuelve la ruta local, la URL pública (si está configurada) y el total.
    Marca al lead como ALTA y deja registro del envío.
    """
    p = catalogo.producto(datos.producto)
    if not p:
        return {"error": f"Producto '{datos.producto}' no encontrado"}

    lead = leads.obtener(datos.lead_id)
    if not lead:
        return {"error": f"Lead {datos.lead_id} no encontrado"}
    if not lead.get("empresa") or not lead.get("cuit"):
        return {
            "error": "El lead no tiene empresa o CUIT cargados. Pedirlos antes de cotizar.",
            "lead": lead,
        }
    if not cuit_mod.es_valido(lead["cuit"]):
        return {"error": f"CUIT inválido en el lead: {lead['cuit']}"}

    numero = f"CD-{datetime.now().strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}"
    archivo = config.PRESUPUESTOS_DIR / f"{numero}.pdf"

    items = [
        pdf_mod.Item(
            descripcion=it.descripcion,
            cantidad=it.cantidad,
            precio_unitario=it.precio_unitario,
        )
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
    """
    Lista los pipelines de Kommo con sus statuses (estados).

    Usalo una vez para descubrir los IDs de pipeline y status que después
    vas a pasar a `kommo_mover_lead` / `kommo_crear_lead`. Idealmente cargá
    esos IDs en el .env (KOMMO_PIPELINE_ID, KOMMO_STATUS_*) para no
    consultarlos en cada llamada.
    """
    return _kommo_safe(kommo.listar_pipelines)


@mcp.tool
def kommo_listar_usuarios() -> dict[str, Any]:
    """
    Lista los usuarios de Kommo con sus IDs (para asignar como responsables).
    """
    return _kommo_safe(kommo.listar_usuarios)


@mcp.tool
def kommo_buscar_lead(query: str, limit: int = 10) -> dict[str, Any]:
    """
    Busca leads en Kommo por texto libre (nombre, teléfono, email, etc.).
    Útil para chequear si un lead ya existe antes de crearlo.
    """
    return _kommo_safe(kommo.buscar_leads, query, limit)


@mcp.tool
def kommo_obtener_lead(lead_id: int) -> dict[str, Any]:
    """Devuelve un lead de Kommo por ID, con sus contactos asociados."""
    return _kommo_safe(kommo.obtener_lead, lead_id)


class KommoCrearLeadInput(BaseModel):
    name: str = Field(..., description="Nombre del lead (ej: 'Pauta Meta - Juan Pérez').")
    contacto_nombre: str | None = None
    contacto_telefono: str | None = Field(None, description="Teléfono en formato internacional, ej +5491155551234.")
    contacto_email: str | None = None
    empresa_nombre: str | None = None
    pipeline_id: int | None = Field(None, description="Si se omite, usa KOMMO_PIPELINE_ID del .env.")
    status_id: int | None = Field(None, description="Si se omite, Kommo lo pone en el primer status del pipeline.")
    responsible_user_id: int | None = Field(None, description="Si se omite, usa KOMMO_RESPONSABLE_DEFAULT_ID del .env.")
    price: int | None = None
    tags: list[str] | None = None


@mcp.tool
def kommo_crear_lead(datos: KommoCrearLeadInput) -> dict[str, Any]:
    """
    Crea un lead en Kommo (con su contacto y opcionalmente compañía) en una
    sola operación. Devuelve el lead creado con su ID.

    Si no pasás pipeline_id / responsible_user_id, se usan los valores por
    defecto del .env (KOMMO_PIPELINE_ID, KOMMO_RESPONSABLE_DEFAULT_ID).
    """
    payload = datos.model_dump()
    payload["pipeline_id"] = payload.get("pipeline_id") or config.KOMMO_PIPELINE_ID
    payload["responsible_user_id"] = (
        payload.get("responsible_user_id") or config.KOMMO_RESPONSABLE_DEFAULT_ID
    )
    return _kommo_safe(kommo.crear_lead_complejo, **payload)


class KommoActualizarLeadInput(BaseModel):
    lead_id: int
    name: str | None = None
    pipeline_id: int | None = None
    status_id: int | None = None
    responsible_user_id: int | None = None
    price: int | None = None


@mcp.tool
def kommo_actualizar_lead(datos: KommoActualizarLeadInput) -> dict[str, Any]:
    """
    Actualiza campos de un lead en Kommo (nombre, pipeline, status, responsable, precio).
    Pasá solo los campos que querés modificar.
    """
    return _kommo_safe(
        kommo.actualizar_lead,
        datos.lead_id,
        name=datos.name,
        pipeline_id=datos.pipeline_id,
        status_id=datos.status_id,
        responsible_user_id=datos.responsible_user_id,
        price=datos.price,
    )


@mcp.tool
def kommo_mover_lead(
    lead_id: int,
    status_id: int | None = None,
    clasificacion: str | None = None,
    pipeline_id: int | None = None,
) -> dict[str, Any]:
    """
    Mueve un lead a otro estado/etapa en Kommo.

    Podés pasar:
      - `status_id` directo (ID de Kommo), o
      - `clasificacion` (INICIAL/MEDIA/ALTA/DESCARTADO) y se resuelve usando
        los IDs configurados en el .env (KOMMO_STATUS_*).
    """
    if status_id is None and clasificacion:
        status_id = _status_id_para_clasificacion(clasificacion.upper())
        if status_id is None:
            return {
                "error": f"No hay KOMMO_STATUS_*_ID configurado para clasificacion '{clasificacion}'.",
            }
    if status_id is None:
        return {"error": "Debe pasarse status_id o clasificacion."}
    return _kommo_safe(
        kommo.actualizar_lead,
        lead_id,
        status_id=status_id,
        pipeline_id=pipeline_id or config.KOMMO_PIPELINE_ID,
    )


@mcp.tool
def kommo_asignar_responsable(lead_id: int, responsible_user_id: int) -> dict[str, Any]:
    """Asigna (o cambia) el usuario responsable de un lead en Kommo."""
    return _kommo_safe(
        kommo.actualizar_lead, lead_id, responsible_user_id=responsible_user_id
    )


@mcp.tool
def kommo_agregar_nota(lead_id: int, texto: str) -> dict[str, Any]:
    """
    Agrega una nota al historial del lead en Kommo. Útil para dejar trazas
    de la conversación, el motivo de un descarte, o que se envió presupuesto.
    """
    return _kommo_safe(kommo.agregar_nota, lead_id, texto)


class KommoCrearTareaInput(BaseModel):
    lead_id: int
    texto: str = Field(..., description="Descripción de la tarea, ej 'Llamar para coordinar reunión'.")
    vencimiento_unix: int = Field(..., description="Timestamp UNIX (segundos) de vencimiento.")
    responsible_user_id: int | None = None
    task_type_id: int | None = Field(None, description="Tipo de tarea (1=Follow-up, 2=Call, 3=Meeting por defecto en Kommo).")


@mcp.tool
def kommo_crear_tarea(datos: KommoCrearTareaInput) -> dict[str, Any]:
    """
    Crea una tarea asociada a un lead en Kommo (recordatorio para el equipo
    comercial). Por ejemplo, al pasar un lead a ALTA se puede crear una
    tarea 'Reunión' para el responsable.
    """
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
    async def dispatch(self, request, call_next):  # type: ignore[override]
        if not config.MCP_AUTH_TOKEN:
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        expected = f"Bearer {config.MCP_AUTH_TOKEN}"
        if auth != expected:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


def build_app() -> Starlette:
    mcp_app = mcp.http_app(path="/mcp")
    return Starlette(
        routes=[Mount("/", app=mcp_app)],
        middleware=[Middleware(BearerAuthMiddleware)],
        lifespan=mcp_app.lifespan,
    )


app = build_app()


if __name__ == "__main__":
    uvicorn.run(app, host=config.MCP_HOST, port=config.MCP_PORT)
