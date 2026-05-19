"""Carga del catálogo de productos desde YAML y utilidades de búsqueda."""
from __future__ import annotations

import unicodedata
from functools import lru_cache
from typing import Any

import yaml

from .config import PRODUCTOS_YAML


def _quitar_acentos(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    ).lower()


@lru_cache(maxsize=1)
def cargar() -> dict[str, Any]:
    with PRODUCTOS_YAML.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def recargar() -> dict[str, Any]:
    cargar.cache_clear()
    return cargar()


def productos() -> dict[str, dict[str, Any]]:
    return cargar().get("productos", {})


def producto(clave: str) -> dict[str, Any] | None:
    return productos().get(clave)


def claves_productos() -> list[str]:
    return list(productos().keys())


def identificar_por_texto(texto: str) -> list[tuple[str, int]]:
    """Devuelve [(clave_producto, score)] ordenado por matches de keywords."""
    if not texto:
        return []
    t = _quitar_acentos(texto)
    scores: list[tuple[str, int]] = []
    for clave, datos in productos().items():
        keywords = [_quitar_acentos(k) for k in datos.get("keywords", [])]
        score = sum(1 for k in keywords if k in t)
        if score:
            scores.append((clave, score))
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores
