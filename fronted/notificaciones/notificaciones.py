"""
notificaciones.py — Orquestador de la bandeja de notificaciones de CAMF

Este archivo es el "índice" del paquete de notificaciones. Su único
trabajo es:
    1) Importar cada tipo específico desde su archivo hermano.
    2) Recolectar las notificaciones de todos los tipos.
    3) Devolver una lista uniforme, ordenada por urgencia.

Cada tipo de notificación vive en su propio archivo dentro del paquete
`notificaciones/`. Los helpers reutilizables (fechas, equipos, grupos)
viven en `_helpers.py`.

Formato de cada notificación (dict). Los campos vienen estructurados —
sin pre-concatenar strings — para que el consumidor decida cómo
presentarlos según el espacio disponible:

    {
        "tipo":             str,   # identificador estable ('responsable_pendiente')
        "mantenimiento_id": int,
        "equipo_resumen":   str,   # 'TG-03' | '4 equipos' | 'sin equipo'
        "grupo_ruta":       str,   # 'UPAEP › Edificio K' | '' si no aplica
        "tipo_mantto":      str,   # 'Preventivo recurrente'
        "fecha_orden":      str,   # 'YYYY-MM-DD HH:MM' para sort
        "fecha_display":    str,   # '1/jul 8:00'
        "accion_tipo":      str,   # 'asignar_responsable'
    }

Diseño deliberado: no se persiste nada en BD para los tipos derivables
del estado canónico. Cada llamada recalcula desde `mantenimientos`.
Esto evita una tabla que tendría que mantenerse sincronizada con
cancelaciones, ediciones, asignaciones, etc. La fuente de verdad es
siempre el estado actual de las tablas de negocio.

Para agregar un nuevo tipo de notificación:
    1) Crear archivo `notificaciones/<nombre>.py` con una función
       pública `obtener() -> List[Dict]`.
    2) Importarla aquí arriba con alias descriptivo.
    3) Agregarla al pipeline en `obtener_notificaciones_activas()`.
"""
from typing import List, Dict, Any

from .responsable_pendiente import obtener as _obtener_responsable_pendiente
from .archivado_exito import obtener as _obtener_archivado_exito
from .archivado_fallo import obtener as _obtener_archivado_fallo


# ──────────────────────────────────────────────────────────────────────
#  API pública
# ──────────────────────────────────────────────────────────────────────
def obtener_notificaciones_activas() -> List[Dict[str, Any]]:
    """Devuelve todas las notificaciones que requieren acción del usuario,
    ordenadas por urgencia (la más próxima primero).

    Si la BD no existe o falla algo, cada tipo devuelve lista vacía
    (no rompe el UI).
    """
    notifs: List[Dict[str, Any]] = []
    notifs.extend(_obtener_responsable_pendiente())
    notifs.extend(_obtener_archivado_fallo())
    notifs.extend(_obtener_archivado_exito())
    # Para agregar más tipos: notifs.extend(_obtener_otro_tipo())
    notifs.sort(key=lambda n: n.get("fecha_orden", ""))
    return notifs
