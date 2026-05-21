"""Carga de configuración desde .env y constantes de rutas."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
PRESUPUESTOS_DIR = DATA_DIR / "presupuestos"
PRODUCTOS_YAML = DATA_DIR / "productos.yaml"
DB_PATH = DATA_DIR / "leads.db"

load_dotenv(ROOT_DIR / ".env")

MCP_HOST = os.getenv("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.getenv("MCP_PORT", "8765"))
MCP_AUTH_TOKEN = os.getenv("MCP_AUTH_TOKEN", "")

EMPRESA_NOMBRE = os.getenv("EMPRESA_NOMBRE", "Consultoría Digital")
EMPRESA_CUIT = os.getenv("EMPRESA_CUIT", "")
EMPRESA_EMAIL = os.getenv("EMPRESA_EMAIL", "")
EMPRESA_TELEFONO = os.getenv("EMPRESA_TELEFONO", "")
EMPRESA_WEB = os.getenv("EMPRESA_WEB", "")

PRESUPUESTOS_BASE_URL = os.getenv("PRESUPUESTOS_BASE_URL", "").rstrip("/")
PRESUPUESTO_VALIDEZ_DIAS = int(os.getenv("PRESUPUESTO_VALIDEZ_DIAS", "15"))


def _int_or_none(name: str) -> int | None:
    v = os.getenv(name, "").strip()
    return int(v) if v.isdigit() else None


KOMMO_SUBDOMAIN = os.getenv("KOMMO_SUBDOMAIN", "").strip()
KOMMO_ACCESS_TOKEN = os.getenv("KOMMO_ACCESS_TOKEN", "").strip()
KOMMO_PIPELINE_ID = _int_or_none("KOMMO_PIPELINE_ID")
KOMMO_STATUS_INICIAL_ID = _int_or_none("KOMMO_STATUS_INICIAL_ID")
KOMMO_STATUS_MEDIA_ID = _int_or_none("KOMMO_STATUS_MEDIA_ID")
KOMMO_STATUS_ALTA_ID = _int_or_none("KOMMO_STATUS_ALTA_ID")
KOMMO_STATUS_DESCARTADO_ID = _int_or_none("KOMMO_STATUS_DESCARTADO_ID")
KOMMO_RESPONSABLE_DEFAULT_ID = _int_or_none("KOMMO_RESPONSABLE_DEFAULT_ID")

GOOGLE_CALENDAR_CLIENT_ID = os.getenv("GOOGLE_CALENDAR_CLIENT_ID", "").strip()
GOOGLE_CALENDAR_CLIENT_SECRET = os.getenv("GOOGLE_CALENDAR_CLIENT_SECRET", "").strip()
GOOGLE_CALENDAR_REFRESH_TOKEN = os.getenv("GOOGLE_CALENDAR_REFRESH_TOKEN", "").strip()
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary").strip()
GOOGLE_CALENDAR_TIMEZONE = os.getenv("GOOGLE_CALENDAR_TIMEZONE", "America/Argentina/Buenos_Aires").strip()
GOOGLE_CALENDAR_DURACION_DEFAULT_MIN = int(os.getenv("GOOGLE_CALENDAR_DURACION_DEFAULT_MIN", "30"))

PRESUPUESTOS_DIR.mkdir(parents=True, exist_ok=True)
