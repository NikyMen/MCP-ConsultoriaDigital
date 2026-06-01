"""Validación de CUIT/CUIL argentino (solo requisitos numéricos mínimos)."""
from __future__ import annotations

import re


def normalizar(cuit: str) -> str:
    """Saca guiones, espacios y puntos."""
    return re.sub(r"\D", "", cuit or "")


def es_valido(cuit: str) -> bool:
    """True si el CUIT/CUIL son 11 dígitos numéricos. No valida dígito verificador ni prefijo."""
    n = normalizar(cuit)
    return len(n) == 11 and n.isdigit()


def formatear(cuit: str) -> str:
    """Devuelve el CUIT en formato XX-XXXXXXXX-X, o el original si no se puede."""
    n = normalizar(cuit)
    if len(n) == 11:
        return f"{n[:2]}-{n[2:10]}-{n[10]}"
    return cuit
