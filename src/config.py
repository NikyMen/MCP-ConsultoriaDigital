"""Carga de configuración desde .env y constantes de rutas."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
PRODUCTOS_YAML = DATA_DIR / "productos.yaml"
PRESUPUESTOS_DIR = DATA_DIR / "presupuestos"

load_dotenv(ROOT_DIR / ".env")

MCP_HOST = os.getenv("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.getenv("MCP_PORT", "8765"))
MCP_AUTH_TOKEN = os.getenv("MCP_AUTH_TOKEN", "")

# URL pública base desde donde se sirven los PDFs de presupuesto (sin barra
# final). Si está seteada, el MCP devuelve la URL completa del PDF a enviar.
# Ej: https://tu-dominio.com/presupuestos
PRESUPUESTOS_BASE_URL = os.getenv("PRESUPUESTOS_BASE_URL", "").rstrip("/")

ROOT_WEB_DIR = ROOT_DIR / "web"

# Token para acceder al panel web (/panel y /api/*). Si está vacío, el panel
# queda público. Se pasa como ?token=... o header Authorization: Bearer ...
PANEL_TOKEN = os.getenv("PANEL_TOKEN", "")

EMPRESA_NOMBRE = os.getenv("EMPRESA_NOMBRE", "Consultoría Digital")
EMPRESA_CUIT = os.getenv("EMPRESA_CUIT", "")
EMPRESA_EMAIL = os.getenv("EMPRESA_EMAIL", "")
EMPRESA_TELEFONO = os.getenv("EMPRESA_TELEFONO", "")
EMPRESA_WEB = os.getenv("EMPRESA_WEB", "")
