"""Validación de CUIT/CUIL argentino (algoritmo del dígito verificador AFIP)."""
from __future__ import annotations

import re

_MULTIPLICADORES = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
_PREFIJOS_VALIDOS = {"20", "23", "24", "25", "26", "27", "30", "33", "34"}


def normalizar(cuit: str) -> str:
    """Saca guiones, espacios y puntos."""
    return re.sub(r"\D", "", cuit or "")


def es_valido(cuit: str) -> bool:
    """True si el CUIT tiene 11 dígitos, prefijo válido y dígito verificador correcto."""
    n = normalizar(cuit)
    if len(n) != 11 or not n.isdigit():
        return False
    if n[:2] not in _PREFIJOS_VALIDOS:
        return False

    suma = sum(int(d) * m for d, m in zip(n[:10], _MULTIPLICADORES))
    resto = suma % 11
    dv_calc = 11 - resto
    if dv_calc == 11:
        dv_calc = 0
    elif dv_calc == 10:
        return False
    return dv_calc == int(n[10])


def formatear(cuit: str) -> str:
    """Devuelve el CUIT en formato XX-XXXXXXXX-X, o el original si no se puede."""
    n = normalizar(cuit)
    if len(n) == 11:
        return f"{n[:2]}-{n[2:10]}-{n[10]}"
    return cuit
