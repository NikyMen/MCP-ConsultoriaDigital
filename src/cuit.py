"""Validacion de CUIT/CUIL argentino."""
from __future__ import annotations

import re

PESOS_VERIFICADOR = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)


def normalizar(cuit: str) -> str:
    """Saca guiones, espacios, puntos y cualquier caracter no numerico."""
    return re.sub(r"\D", "", cuit or "")


def digito_verificador(cuit_normalizado: str) -> str | None:
    """Calcula el digito verificador para los primeros 10 digitos."""
    if len(cuit_normalizado) < 10 or not cuit_normalizado[:10].isdigit():
        return None

    suma = sum(int(d) * p for d, p in zip(cuit_normalizado[:10], PESOS_VERIFICADOR))
    resultado = 11 - (suma % 11)

    if resultado == 11:
        return "0"
    if resultado == 10:
        return None
    return str(resultado)


def es_valido(cuit: str) -> bool:
    """True si tiene 11 digitos y el digito verificador es correcto."""
    n = normalizar(cuit)
    if len(n) != 11 or not n.isdigit():
        return False
    return digito_verificador(n) == n[-1]


def formatear(cuit: str) -> str:
    """Devuelve el CUIT/CUIL en formato XX-XXXXXXXX-X, o el original si no se puede."""
    n = normalizar(cuit)
    if len(n) == 11:
        return f"{n[:2]}-{n[2:10]}-{n[10]}"
    return cuit
