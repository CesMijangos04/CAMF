"""
_helpers.py — Utilidades compartidas del paquete notificaciones

Contiene funciones y constantes que pueden usarse desde varios tipos de
notificaciones dentro del paquete. Todo lo específico de UN tipo vive
en el archivo de ese tipo, no aquí.

Las firmas y la lógica de estas funciones no cambiaron respecto al
notificaciones.py monolítico original — el refactor solo movió los
bloques a este archivo.
"""
from datetime import datetime
from typing import Dict, Tuple, Optional


# ──────────────────────────────────────────────────────────────────────
#  Helpers de equipos
# ──────────────────────────────────────────────────────────────────────
def _resumen_equipos(equipos_rows) -> str:
    """'TG-03' si hay uno, '4 equipos' si hay varios, 'sin equipo' si no hay."""
    n = len(equipos_rows)
    if n == 0:
        return "sin equipo"
    if n == 1:
        return str(equipos_rows[0][0])
    return f"{n} equipos"


# ──────────────────────────────────────────────────────────────────────
#  Helpers de grupos
#
#  Replicados de programados.py para que el paquete notificaciones sea
#  autónomo (no depende de un módulo de UI). Si en el futuro un tercer
#  consumidor los necesita, se extraen a un módulo común tipo
#  `grupos_helpers.py` o se mueven a db_manager.py.
# ──────────────────────────────────────────────────────────────────────
def _cargar_jerarquia_grupos(cur) -> Dict[int, Tuple[str, Optional[int]]]:
    """{grupo_id: (nombre, padre_id)} para todos los grupos."""
    try:
        rows = cur.execute("SELECT id, nombre, padre_id FROM grupos").fetchall()
    except Exception:
        return {}
    return {g[0]: (g[1], g[2]) for g in rows}


def _cargar_grupos_de_equipos(cur) -> Dict[Tuple[str, str], Optional[int]]:
    """{(equipo_id, tabla): grupo_id} consultando tableros y transformadores."""
    d: Dict[Tuple[str, str], Optional[int]] = {}
    for tabla in ("tableros", "transformadores"):
        try:
            rows = cur.execute(f"SELECT id, grupo_id FROM {tabla}").fetchall()
        except Exception:
            continue
        for eq_id, grupo_id in rows:
            d[(eq_id, tabla)] = grupo_id
    return d


def _ancestros(grupo_id, jerarquia):
    """Lista de IDs desde el grupo hasta la raíz (incluye el grupo mismo)."""
    out = []
    actual = grupo_id
    visitados = set()  # anti-ciclo si los datos vienen corruptos
    while actual is not None and actual in jerarquia and actual not in visitados:
        visitados.add(actual)
        out.append(actual)
        actual = jerarquia[actual][1]
    return out


def _ruta_grupo(grupo_id, jerarquia) -> str:
    """'Edificio A › Piso 2' desde la raíz hasta el grupo dado."""
    if grupo_id is None or grupo_id not in jerarquia:
        return ""
    partes = []
    actual = grupo_id
    visitados = set()
    while actual is not None and actual in jerarquia and actual not in visitados:
        visitados.add(actual)
        partes.append(jerarquia[actual][0])
        actual = jerarquia[actual][1]
    return " › ".join(reversed(partes))


def _grupo_comun(equipos, grupo_por_equipo, jerarquia):
    """Grupo común más específico para una lista de equipos. None si
    algún equipo no tiene grupo o no hay ancestro común."""
    if not equipos:
        return None
    listas = []
    for eq_id, eq_tipo in equipos:
        grupo = grupo_por_equipo.get((eq_id, eq_tipo))
        if grupo is None:
            return None
        listas.append(_ancestros(grupo, jerarquia))
    for g in listas[0]:
        if all(g in lista for lista in listas[1:]):
            return g
    return None


# ──────────────────────────────────────────────────────────────────────
#  Helper de fecha
# ──────────────────────────────────────────────────────────────────────
_MESES_ES = ["", "ene", "feb", "mar", "abr", "may", "jun",
             "jul", "ago", "sep", "oct", "nov", "dic"]


def _fecha_corta(fecha_str) -> str:
    """'2026-06-30 08:00' → '30/jun 8:00'. Tolerante a valores raros."""
    if not fecha_str:
        return ""
    try:
        dt = datetime.strptime(fecha_str, "%Y-%m-%d %H:%M")
        hora = dt.strftime("%H:%M").lstrip("0") or "0:00"
        return f"{dt.day}/{_MESES_ES[dt.month]} {hora}"
    except Exception:
        return str(fecha_str)
