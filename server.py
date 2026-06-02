"""
MCP server de Consultoría Digital.

Servidor MCP *sin estado*: solo expone información del catálogo de productos,
los PDFs de presupuesto y la validación de CUIT. No persiste leads ni chats.

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
from typing import Any

import uvicorn
from fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from src import (
    catalogo,
    config,
    cuit as cuit_mod,
    store,
)

# ---------------------------------------------------------------------------
# Inicialización
# ---------------------------------------------------------------------------
mcp = FastMCP(name="Consultoria Digital MCP")


class LooseModel(BaseModel):
    """Modelo base que ignora cualquier campo extra que mande el cliente."""

    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Tools: productos / FAQs
# ---------------------------------------------------------------------------

class ProductoKeyInput(LooseModel):
    producto: str = Field(..., description="Clave del producto: gestion_redes, pauta_meta, crm, concilia, turneria, desarrollo_software.")


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
    """Información detallada de un producto: nombre, descripción, problema que
    resuelve, beneficios, cómo funciona, para quién es ideal, qué incluye y precio."""
    p = catalogo.producto(datos.producto)
    if not p:
        return {"error": f"Producto '{datos.producto}' no encontrado", "claves_validas": catalogo.claves_productos()}
    return {
        "clave": datos.producto,
        "nombre": p.get("nombre"),
        "descripcion": p.get("descripcion"),
        "problema": p.get("problema"),
        "beneficios": p.get("beneficios", []),
        "como_funciona": p.get("como_funciona", []),
        "integraciones": p.get("integraciones", []),
        "ideal_para": p.get("ideal_para"),
        "incluye": p.get("incluye", []),
        # Sin precios: la cotización vive solo en el PDF de presupuesto.
        # Usá la tool `presupuesto_pdf` para saber qué PDF enviar.
        "tiene_presupuesto_pdf": bool(p.get("presupuesto")),
        "nota_precio": "Los precios no se dicen por chat: se envían en el PDF de presupuesto (tool presupuesto_pdf).",
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
# Tools: presupuestos (PDF a enviar) — el MCP NO cotiza ni dice precios
# ---------------------------------------------------------------------------

def _presupuesto_payload(clave_presupuesto: str) -> dict[str, Any] | None:
    """Arma el item del PDF a enviar: archivo, etiqueta y (si hay base URL) la URL pública."""
    pres = catalogo.presupuesto(clave_presupuesto)
    if not pres:
        return None
    archivo = pres.get("archivo")
    item: dict[str, Any] = {
        "clave": clave_presupuesto,
        "archivo": archivo,
        "etiqueta": pres.get("etiqueta"),
        "cubre": pres.get("cubre", []),
    }
    if config.PRESUPUESTOS_BASE_URL and archivo:
        item["url"] = f"{config.PRESUPUESTOS_BASE_URL}/{archivo}"
    return item


@mcp.tool
def presupuesto_pdf(datos: ProductoKeyInput) -> dict[str, Any]:
    """Devuelve el NOMBRE del PDF de presupuesto que hay que enviarle al lead
    según el producto que le interesa. NO devuelve precios ni montos: la
    cotización vive solo dentro del PDF. Si el producto no tiene PDF estándar
    (p. ej. desarrollo a medida), avisa que se cotiza tras un relevamiento.
    Usá `archivo` (y `url` si está disponible) para que n8n adjunte/envíe el PDF.
    """
    if datos.producto not in catalogo.claves_productos():
        return {"error": f"Producto '{datos.producto}' no encontrado", "claves_validas": catalogo.claves_productos()}
    clave_pres = catalogo.presupuesto_de_producto(datos.producto)
    if not clave_pres:
        return {
            "producto": datos.producto,
            "hay_pdf": False,
            "motivo": "Este servicio se cotiza a medida tras un relevamiento sin cargo; no hay PDF estándar.",
        }
    item = _presupuesto_payload(clave_pres)
    if not item:
        return {
            "producto": datos.producto,
            "hay_pdf": False,
            "error": f"El producto apunta al presupuesto '{clave_pres}' pero no está definido en el catálogo.",
        }
    return {"producto": datos.producto, "hay_pdf": True, "presupuesto": item}


@mcp.tool
def presupuestos_disponibles() -> dict[str, Any]:
    """Lista todos los PDFs de presupuesto disponibles, con su nombre de archivo,
    etiqueta y qué productos cubre cada uno."""
    return {
        "presupuestos": [
            _presupuesto_payload(clave) for clave in catalogo.presupuestos().keys()
        ]
    }


# ---------------------------------------------------------------------------
# Tools: CUIT
# ---------------------------------------------------------------------------

class CuitInput(LooseModel):
    cuit: str = Field(..., description="CUIT/CUIL argentino en cualquier formato (con o sin guiones).")


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
# Tools: registro de mensajes (alimenta el panel /panel)
# ---------------------------------------------------------------------------

class RegistrarMensajeInput(LooseModel):
    telefono: str = Field(..., description="Teléfono del lead (identificador de la conversación).")
    texto: str = Field(..., description="Contenido del mensaje.")
    rol: str = Field("cliente", description="Quién lo envió: 'cliente' o 'bot'.")
    nombre: str | None = Field(None, description="Nombre del lead, si se conoce.")
    producto_interes: str | None = Field(None, description="Clave del producto de interés detectado.")
    clasificacion: str | None = Field(
        None,
        description="Estado del lead: NUEVO, EN_CONVERSACION, CALIFICADO, PRESUPUESTO_ENVIADO, CERRADO, DESCARTADO.",
    )
    cuit: str | None = Field(None, description="CUIT del lead, si se obtuvo.")
    cuit_valido: bool | None = Field(None, description="Si el CUIT fue validado como correcto.")


@mcp.tool
def registrar_mensaje(datos: RegistrarMensajeInput) -> dict[str, Any]:
    """Guarda un mensaje recibido (o enviado) y crea/actualiza el lead asociado
    por teléfono, con su clasificación y producto de interés. Alimenta el panel
    web de mensajes clasificados (/panel). Llamala desde n8n por cada mensaje."""
    try:
        return {"ok": True, **store.registrar_mensaje(
            telefono=datos.telefono,
            texto=datos.texto,
            rol=datos.rol,
            nombre=datos.nombre,
            producto_interes=datos.producto_interes,
            clasificacion=datos.clasificacion,
            cuit=datos.cuit,
            cuit_valido=datos.cuit_valido,
        )}
    except ValueError as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Tools: utilitarias
# ---------------------------------------------------------------------------

@mcp.tool
def recargar_catalogo() -> dict[str, Any]:
    """Recarga el catálogo de productos desde productos.yaml sin reiniciar el server."""
    data = catalogo.recargar()
    return {"productos_cargados": list(data.get("productos", {}).keys())}


# ---------------------------------------------------------------------------
# Bearer auth (opcional) y arranque
# ---------------------------------------------------------------------------

class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Bearer auth para el MCP (/mcp)."""

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
N8N_ENVELOPE_FIELDS = frozenset({"text", "num", "toolCallId", "sessionId", "tool"})


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


# ---------------------------------------------------------------------------
# Panel web: /panel (HTML) + /api/mensajes (JSON), protegidos por PANEL_TOKEN
# ---------------------------------------------------------------------------

def _panel_autorizado(request) -> bool:
    """True si no hay token configurado o si el request trae el token correcto."""
    if not config.PANEL_TOKEN:
        return True
    token = request.query_params.get("token")
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            token = auth[len("Bearer "):]
    return token == config.PANEL_TOKEN


async def panel_html(request):
    if not _panel_autorizado(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return FileResponse(config.ROOT_WEB_DIR / "panel.html")


async def api_mensajes(request):
    if not _panel_autorizado(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    clasif = request.query_params.get("clasificacion") or None
    producto = request.query_params.get("producto") or None
    try:
        limit = int(request.query_params.get("limit", "500"))
    except ValueError:
        limit = 500
    return JSONResponse({
        "mensajes": store.listar_mensajes(clasificacion=clasif, producto=producto, limit=limit),
        "resumen": store.resumen(),
    })


def build_app() -> Starlette:
    store.init_db()
    mcp_app = mcp.http_app(path="/mcp")
    wrapped_mcp = StripN8nEnvelopeMiddleware(mcp_app)

    routes = [
        Route("/panel", panel_html),
        Route("/api/mensajes", api_mensajes),
    ]
    # PDFs de presupuesto servidos como archivos estáticos en /presupuestos.
    # Público (el BearerAuthMiddleware solo protege /mcp) para que WaSender /
    # WhatsApp puedan descargarlos por URL. Se monta solo si la carpeta existe.
    if config.PRESUPUESTOS_DIR.is_dir():
        routes.append(
            Mount(
                "/presupuestos",
                app=StaticFiles(directory=str(config.PRESUPUESTOS_DIR)),
            )
        )
    # MCP server (bearer auth) montado en /mcp (el "/" captura todo lo demás).
    routes.append(Mount("/", app=wrapped_mcp))

    return Starlette(
        routes=routes,
        middleware=[Middleware(BearerAuthMiddleware)],
        lifespan=mcp_app.lifespan,
    )


app = build_app()


if __name__ == "__main__":
    uvicorn.run(app, host=config.MCP_HOST, port=config.MCP_PORT)
