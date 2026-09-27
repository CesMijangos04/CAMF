"""
responsable_pendiente.py — Tipo de notificación: responsable pendiente

Mantenimientos auto-generados por una serie recurrente que aún no
tienen responsable asignado (responsable_tipo='pendiente').

Fuente de verdad: se deriva siempre del estado actual de la tabla
`mantenimientos`. No se persiste nada — cuando el usuario asigna el
responsable, el estado cambia y la notificación desaparece sola.

La lógica de esta función no cambió respecto al notificaciones.py
monolítico original (antes se llamaba `_notif_responsable_pendiente`).
El refactor solo movió el bloque a este archivo y renombró la función
pública a `obtener()` para uniformidad entre tipos.
"""
from typing import List, Dict, Any

from db_manager import connect_db
from ._helpers import (
    _resumen_equipos,
    _cargar_jerarquia_grupos,
    _cargar_grupos_de_equipos,
    _grupo_comun,
    _ruta_grupo,
    _fecha_corta,
)


def obtener() -> List[Dict[str, Any]]:
    """Devuelve la lista de notificaciones activas de este tipo."""
    conn = connect_db(create_if_missing=False)
    if conn is None:
        return []

    out: List[Dict[str, Any]] = []
    try:
        cur = conn.cursor()

        # Pre-cargar jerarquía y mapa de grupos por equipo (una vez por
        # llamada, no por cada mantenimiento, para no machacar la BD).
        jerarquia = _cargar_jerarquia_grupos(cur)
        grupo_por_equipo = _cargar_grupos_de_equipos(cur)

        # IDs de mantenimientos pendientes de responsable
        filas = cur.execute("""
            SELECT id, tipo_mantenimiento, fecha_inicio,
                   COALESCE(es_recurrente, 0) AS es_rec
            FROM mantenimientos
            WHERE responsable_tipo = 'pendiente'
              AND fecha_cierre IS NULL
            ORDER BY fecha_inicio ASC
        """).fetchall()

        for mid, tipo_m, fini, es_rec in filas:
            equipos_rows = cur.execute("""
                SELECT equipo_id, equipo_tipo
                FROM mantenimientos_equipos
                WHERE mantenimiento_id = ?
            """, (mid,)).fetchall()

            equipo_resumen = _resumen_equipos(equipos_rows)
            grupo_comun_id = _grupo_comun(equipos_rows, grupo_por_equipo, jerarquia)
            grupo_ruta = _ruta_grupo(grupo_comun_id, jerarquia)

            tipo_label = (tipo_m or "Mantenimiento").capitalize()
            tipo_mantto = f"{tipo_label} recurrente" if es_rec else tipo_label

            out.append({
                "tipo":             "responsable_pendiente",
                "mantenimiento_id": mid,
                "equipo_resumen":   equipo_resumen,
                "grupo_ruta":       grupo_ruta,
                "tipo_mantto":      tipo_mantto,
                "fecha_orden":      fini or "",
                "fecha_display":    _fecha_corta(fini),
                "accion_tipo":      "asignar_responsable",
            })
    except Exception as e:
        print(f"[notificaciones/responsable_pendiente] error: {e}")
    finally:
        conn.close()

    return out
