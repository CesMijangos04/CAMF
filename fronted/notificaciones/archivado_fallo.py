"""
archivado_fallo.py — Tipo de notificación: archivado con fallo pendiente

Se dispara cuando la última migración anual al archivo histórico falló
y el usuario aún no ha reintentado con éxito.

Fuente de verdad: la clave `notif_archivo_fallo_msg` en la tabla
metadata_sistema. Si tiene contenido, hay un fallo pendiente.
La setea `migracion_archivo._marcar_fallo()` cuando algo sale mal, y
la borra `migracion_archivo.ejecutar_migracion_anual()` al terminar
con éxito (incluye el caso de reintento manual).

Al hacer clic, inicio.py abre un diálogo con el mensaje técnico del
error y un botón para reintentar. Si el reintento tiene éxito, la
notificación de fallo desaparece automáticamente en el próximo refresh
de Inicio (porque se borró el flag).
"""
from typing import List, Dict, Any

from db_manager import metadata_get


def obtener() -> List[Dict[str, Any]]:
    """Devuelve la lista con la notificación de fallo activa (0 o 1
    elemento — solo puede haber un fallo pendiente a la vez)."""
    msg = metadata_get("notif_archivo_fallo_msg", "")

    # Sin mensaje = sin fallo pendiente.
    if not msg:
        return []

    # Ordenamos con fecha_orden vacía como el éxito para que caiga junto
    # con él. La UI decide si darle más peso visual por el tipo.
    return [{
        "tipo":             "archivado_fallo",
        "mantenimiento_id": 0,  # No aplica a este tipo.
        "equipo_resumen":   "No se pudo archivar",
        "grupo_ruta":       "Haz clic para reintentar",
        "tipo_mantto":      "Archivado histórico",
        "fecha_orden":      "",
        "fecha_display":    "",
        "accion_tipo":      "reintentar_archivado",
    }]
