"""Operaciones sobre leads y eventos."""
from __future__ import annotations

from typing import Any

from .db import get_conn, now_iso

VALIDAS = {
    "INICIAL",
    "PRODUCTO_IDENTIFICADO",
    "MEDIA",
    "ALTA",
    "DESCARTADO",
}


def _row_to_dict(row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def buscar_por_telefono(telefono: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM leads WHERE telefono = ? ORDER BY id DESC LIMIT 1",
            (telefono,),
        ).fetchone()
        return _row_to_dict(row) if row else None


def obtener(lead_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        return _row_to_dict(row) if row else None


def upsert(
    *,
    telefono: str | None = None,
    nombre: str | None = None,
    empresa: str | None = None,
    cuit: str | None = None,
    producto_interes: str | None = None,
    clasificacion: str | None = None,
    notas: str | None = None,
) -> dict[str, Any]:
    """Crea o actualiza un lead. Si llega un teléfono que ya existe, lo actualiza."""
    existente = buscar_por_telefono(telefono) if telefono else None
    ts = now_iso()

    if existente:
        campos = {
            "nombre": nombre or existente["nombre"],
            "empresa": empresa or existente["empresa"],
            "cuit": cuit or existente["cuit"],
            "producto_interes": producto_interes or existente["producto_interes"],
            "clasificacion": clasificacion or existente["clasificacion"],
            "notas": notas if notas is not None else existente["notas"],
            "actualizado_en": ts,
        }
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE leads SET nombre=?, empresa=?, cuit=?, producto_interes=?,
                       clasificacion=?, notas=?, actualizado_en=?
                WHERE id=?
                """,
                (
                    campos["nombre"],
                    campos["empresa"],
                    campos["cuit"],
                    campos["producto_interes"],
                    campos["clasificacion"],
                    campos["notas"],
                    campos["actualizado_en"],
                    existente["id"],
                ),
            )
        return obtener(existente["id"])  # type: ignore[return-value]

    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO leads (telefono, nombre, empresa, cuit, producto_interes,
                               clasificacion, notas, creado_en, actualizado_en)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                telefono,
                nombre,
                empresa,
                cuit,
                producto_interes,
                clasificacion or "INICIAL",
                notas,
                ts,
                ts,
            ),
        )
        lead_id = int(cur.lastrowid)
    return obtener(lead_id)  # type: ignore[return-value]


def registrar_evento(lead_id: int, tipo: str, detalle: str | None = None) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO eventos (lead_id, tipo, detalle, creado_en) VALUES (?, ?, ?, ?)",
            (lead_id, tipo, detalle, now_iso()),
        )


def listar(
    *,
    clasificacion: str | None = None,
    limit: int = 50,
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


def guardar_presupuesto(
    *, lead_id: int, producto: str, archivo: str, url_publica: str | None, total_ars: float
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO presupuestos (lead_id, producto, archivo, url_publica, total_ars, creado_en)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (lead_id, producto, archivo, url_publica, total_ars, now_iso()),
        )
        return int(cur.lastrowid)
