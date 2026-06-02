"""Persistencia de leads y mensajes en SQLite (data/leads.db).

A diferencia del MCP (que es sin estado), este módulo guarda cada mensaje
recibido y su clasificación, para alimentar el panel web en /panel.

Tablas (creadas con `init_db` si no existen):
    leads(id, telefono UNIQUE, nombre, cuit, cuit_valido, producto_interes,
          clasificacion, nota, creado_en, actualizado_en)
    mensajes(id, lead_id -> leads.id, rol, texto, creado_en)
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from . import config

DB_PATH = config.DATA_DIR / "leads.db"

# Estados de clasificación válidos para un lead.
CLASIFICACIONES = ("NUEVO", "EN_CONVERSACION", "CALIFICADO", "PRESUPUESTO_ENVIADO", "CERRADO", "DESCARTADO")


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Crea las tablas si no existen. Idempotente."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telefono TEXT UNIQUE,
                nombre TEXT,
                cuit TEXT,
                cuit_valido INTEGER NOT NULL DEFAULT 0,
                producto_interes TEXT,
                clasificacion TEXT NOT NULL DEFAULT 'NUEVO',
                nota TEXT,
                creado_en TEXT NOT NULL,
                actualizado_en TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS mensajes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
                rol TEXT NOT NULL,
                texto TEXT NOT NULL,
                creado_en TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_mensajes_lead ON mensajes(lead_id);
            """
        )


def _upsert_lead(
    conn: sqlite3.Connection,
    telefono: str,
    nombre: str | None,
    producto_interes: str | None,
    clasificacion: str | None,
    cuit: str | None,
    cuit_valido: bool | None,
) -> int:
    """Crea o actualiza el lead por teléfono. Devuelve su id.

    Solo pisa columnas para las que se pasó un valor no nulo (no borra datos
    previos con None).
    """
    ahora = _ahora()
    row = conn.execute("SELECT * FROM leads WHERE telefono = ?", (telefono,)).fetchone()
    if row is None:
        conn.execute(
            """INSERT INTO leads
                 (telefono, nombre, cuit, cuit_valido, producto_interes,
                  clasificacion, creado_en, actualizado_en)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                telefono,
                nombre,
                cuit,
                1 if cuit_valido else 0,
                producto_interes,
                clasificacion or "NUEVO",
                ahora,
                ahora,
            ),
        )
        return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

    # Update parcial: solo campos provistos.
    campos: dict[str, Any] = {}
    if nombre is not None:
        campos["nombre"] = nombre
    if producto_interes is not None:
        campos["producto_interes"] = producto_interes
    if clasificacion is not None:
        campos["clasificacion"] = clasificacion
    if cuit is not None:
        campos["cuit"] = cuit
    if cuit_valido is not None:
        campos["cuit_valido"] = 1 if cuit_valido else 0
    campos["actualizado_en"] = ahora
    sets = ", ".join(f"{k} = ?" for k in campos)
    conn.execute(f"UPDATE leads SET {sets} WHERE id = ?", (*campos.values(), row["id"]))
    return int(row["id"])


def registrar_mensaje(
    telefono: str,
    texto: str,
    rol: str = "cliente",
    nombre: str | None = None,
    producto_interes: str | None = None,
    clasificacion: str | None = None,
    cuit: str | None = None,
    cuit_valido: bool | None = None,
) -> dict[str, Any]:
    """Guarda un mensaje y crea/actualiza el lead asociado por teléfono.

    Devuelve {lead_id, mensaje_id}.
    """
    telefono = (telefono or "").strip()
    if not telefono:
        raise ValueError("telefono es obligatorio")
    if clasificacion is not None and clasificacion not in CLASIFICACIONES:
        raise ValueError(f"clasificacion inválida: {clasificacion}. Válidas: {CLASIFICACIONES}")
    with _conn() as conn:
        lead_id = _upsert_lead(
            conn, telefono, nombre, producto_interes, clasificacion, cuit, cuit_valido
        )
        conn.execute(
            "INSERT INTO mensajes (lead_id, rol, texto, creado_en) VALUES (?, ?, ?, ?)",
            (lead_id, rol.strip() or "cliente", texto, _ahora()),
        )
        mensaje_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    return {"lead_id": lead_id, "mensaje_id": mensaje_id}


def listar_mensajes(
    clasificacion: str | None = None,
    producto: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Lista mensajes (más recientes primero) con datos del lead, para el panel."""
    where = []
    params: list[Any] = []
    if clasificacion:
        where.append("l.clasificacion = ?")
        params.append(clasificacion)
    if producto:
        where.append("l.producto_interes = ?")
        params.append(producto)
    clausula = ("WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)
    with _conn() as conn:
        rows = conn.execute(
            f"""SELECT m.id, m.rol, m.texto, m.creado_en,
                       l.id AS lead_id, l.telefono, l.nombre,
                       l.producto_interes, l.clasificacion, l.cuit, l.cuit_valido
                  FROM mensajes m
                  JOIN leads l ON l.id = m.lead_id
                  {clausula}
                 ORDER BY m.creado_en DESC, m.id DESC
                 LIMIT ?""",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def resumen() -> dict[str, Any]:
    """Conteos por clasificación y por producto, para las tarjetas del panel."""
    with _conn() as conn:
        total_leads = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        total_msgs = conn.execute("SELECT COUNT(*) FROM mensajes").fetchone()[0]
        por_clasif = {
            r["clasificacion"]: r["n"]
            for r in conn.execute(
                "SELECT clasificacion, COUNT(*) AS n FROM leads GROUP BY clasificacion"
            )
        }
        por_producto = {
            (r["producto_interes"] or "sin_clasificar"): r["n"]
            for r in conn.execute(
                "SELECT producto_interes, COUNT(*) AS n FROM leads GROUP BY producto_interes"
            )
        }
    return {
        "total_leads": total_leads,
        "total_mensajes": total_msgs,
        "por_clasificacion": por_clasif,
        "por_producto": por_producto,
    }
