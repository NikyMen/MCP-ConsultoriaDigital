"""
MCP server de Consultoría Digital.

Servidor MCP *sin estado*: solo expone información del catálogo de productos
y utilidades (validación de CUIT, system prompt). No persiste leads ni chats.

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
from starlette.responses import JSONResponse
from starlette.routing import Mount

from src import (
    catalogo,
    config,
    cuit as cuit_mod,
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
            # MCP server (bearer auth) montado en /mcp.
            Mount("/", app=wrapped_mcp),
        ],
        middleware=[Middleware(BearerAuthMiddleware)],
        lifespan=mcp_app.lifespan,
    )


app = build_app()


if __name__ == "__main__":
    uvicorn.run(app, host=config.MCP_HOST, port=config.MCP_PORT)
