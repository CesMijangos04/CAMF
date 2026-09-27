"""
archivado_exito.py — Tipo de notificación: archivado exitoso

Se dispara cuando la migración anual al archivo histórico se completó
con éxito y aún no ha sido "leída" (marcada como vista) por el usuario.

Fuente de verdad: las claves `notif_archivo_exito_cantidad` y
`notif_archivo_exito_anio` en la tabla metadata_sistema. Estas claves
las setea `migracion_archivo.ejecutar_migracion_anual()` al terminar
con éxito, y las borra el manejador de clic en inicio.py cuando el
usuario marca la notificación como leída.

Es una notificación de SOLO LECTURA. El clic no abre ningún diálogo ni
lanza ninguna acción — solo la marca como leída y desaparece. El
accion_tipo la distingue del resto para que inicio.py sepa qué hacer.
"""
from typing import List, Dict, Any

from db_manager import metadata_get


def obtener() -> List[Dict[str, Any]]:
    """Devuelve la lista con la notificación de éxito activa (0 o 1
    elemento — nunca más, porque solo hay una migración por año)."""
    cantidad_str = metadata_get("notif_archivo_exito_cantidad")
    anios_str = metadata_get("notif_archivo_exito_anio")

    # Si no hay flag, no hay notificación activa.
    if not cantidad_str or not anios_str:
        return []

    try:
        cantidad = int(cantidad_str)
    except (ValueError, TypeError):
        # Metadata corrupta — mejor no mostrar nada que mostrar basura.
        return []

    # Formato singular/plural para que el texto lea natural.
    if cantidad == 1:
        equipo_resumen = "1 mantenimiento"
    else:
        equipo_resumen = f"{cantidad} mantenimientos"

    # El campo grupo_ruta se usa para el año(s) archivado(s), que es la
    # información contextual relevante para este tipo. Reusamos el campo
    # en vez de introducir uno nuevo — inicio.py solo pinta los campos
    # que existen, así que la estructura se respeta.
    return [{
        "tipo":             "archivado_exito",
        "mantenimiento_id": 0,  # No aplica a este tipo.
        "equipo_resumen":   equipo_resumen,
        "grupo_ruta":       f"Año(s) {anios_str}",
        "tipo_mantto":      "Archivado histórico",
        "fecha_orden":      "",  # Sin fecha específica, ordena al final.
        "fecha_display":    "",
        "accion_tipo":      "marcar_archivado_exito_leido",
    }]
