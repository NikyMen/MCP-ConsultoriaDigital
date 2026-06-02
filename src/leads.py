"""Operaciones sobre leads, notas y mensajes (calificación de la gente)."""
from __future__ import annotations

from typing import Any

from .db import get_conn, now_iso

# Estados de calificación del lead (de menos a más avanzado).
VALIDAS = {
    "NUEVO",
    "INTERESADO",
    "CALIFICADO",          # entregó CUIT válido
    "PRESUPUESTO_ENVIADO",
    "REUNION_AGENDADA",
    "DESCARTADO",
}

ROLES_MENSAJE = {"cliente", "asistente", "sistema"}


def _row_to_dict(row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def buscar_por_telefono(telefono: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM leads WHERE telefono = ?", (telefono,)
        ).fetchone()
        return _row_to_dict(row) if row else None


def obtener(lead_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        return _row_to_dict(row) if row else None


def upsert(
    *,
    telefono: str,
    nombre: str | None = None,
    cuit: str | None = None,
    cuit_valido: bool | None = None,
    producto_interes: str | None = None,
    clasificacion: str | None = None,
    nota: str | None = None,
) -> dict[str, Any]:
    """Crea o actualiza un lead por teléfono. Solo pisa los campos que llegan."""
    existente = buscar_por_telefono(telefono)
    ts = now_iso()

    if existente:
        campos = {
            "nombre": nombre if nombre is not None else existente["nombre"],
            "cuit": cuit if cuit is not None else existente["cuit"],
            "cuit_valido": int(cuit_valido) if cuit_valido is not None else existente["cuit_valido"],
            "producto_interes": producto_interes if producto_interes is not None else existente["producto_interes"],
            "clasificacion": clasificacion or existente["clasificacion"],
            "nota": nota if nota is not None else existente["nota"],
            "actualizado_en": ts,
        }
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE leads SET nombre=?, cuit=?, cuit_valido=?, producto_interes=?,
                       clasificacion=?, nota=?, actualizado_en=?
                WHERE id=?
                """,
                (
                    campos["nombre"],
                    campos["cuit"],
                    campos["cuit_valido"],
                    campos["producto_interes"],
                    campos["clasificacion"],
                    campos["nota"],
                    campos["actualizado_en"],
                    existente["id"],
                ),
            )
        return obtener(existente["id"])  # type: ignore[return-value]

    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO leads (telefono, nombre, cuit, cuit_valido, producto_interes,
                               clasificacion, nota, creado_en, actualizado_en)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                telefono,
                nombre,
                cuit,
                int(cuit_valido) if cuit_valido is not None else 0,
                producto_interes,
                clasificacion or "NUEVO",
                nota,
                ts,
                ts,
            ),
        )
        lead_id = int(cur.lastrowid)
    return obtener(lead_id)  # type: ignore[return-value]


def guardar_mensaje(lead_id: int, rol: str, texto: str) -> int:
    """Guarda un mensaje del chat asociado al lead. rol: cliente | asistente | sistema."""
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO mensajes (lead_id, rol, texto, creado_en) VALUES (?, ?, ?, ?)",
            (lead_id, rol, texto, now_iso()),
        )
        return int(cur.lastrowid)


def mensajes(lead_id: int, limit: int = 200) -> list[dict[str, Any]]:
    """Historial de chat del lead, en orden cronológico (más viejo primero)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM mensajes WHERE lead_id = ? ORDER BY id ASC LIMIT ?",
            (lead_id, limit),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def listar(
    *, clasificacion: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    with get_conn() as conn:
        if clasificacion:
            rows = conn.execute(
                "SELECT * FROM leads WHERE clasificacion = ? ORDER BY actualizado_en DESC LIMIT ?",
                (clasificacion, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM leads ORDER BY actualizado_en DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def estado_completo(telefono: str) -> dict[str, Any] | None:
    """Estado integral por teléfono: datos del lead + nota + historial de chat."""
    lead = buscar_por_telefono(telefono)
    if not lead:
        return None
    return {"lead": lead, "mensajes": mensajes(lead["id"])}
