"""
migracion_archivo.py — Orquestador de la migración anual al archivo histórico

Este módulo coordina TODO el proceso de "archivar años viejos" que
ocurre automáticamente al arrancar CAMF cada año:

    1) Detectar si hay migración pendiente (año actual > último migrado).
    2) Crear respaldo automático de seguridad ANTES de tocar la BD.
    3) Rotar respaldos viejos (mantener solo los 3 más recientes).
    4) Ejecutar la migración SQL en transacción atómica (delegada a
       db_manager.mover_anio_a_archivo() por cada año pendiente).
    5) Actualizar metadata_sistema con el resultado.
    6) Preparar los flags que las notificaciones consumirán en Inicio.

Diseño:
    - Este módulo es 100% lógica y estado, cero UI. La UI (splash,
      notificaciones) es responsabilidad de main.py e inicio.py.
    - En caso de fallo, la BD queda intacta (transacción → rollback) y
      se marca un flag que dispara la notificación clickeable en Inicio
      para que el usuario reintente.

Diccionario de claves usadas en metadata_sistema:
    ultima_migracion_archivo    → año en que corrió con éxito la última
                                   migración (ej. "2027").
    notif_archivo_exito_cantidad → cantidad de mantenimientos movidos en
                                   el último éxito no leído.
    notif_archivo_exito_anio     → año(s) movidos en el último éxito no
                                   leído (ej. "2022" o "2021, 2022").
    notif_archivo_fallo_msg      → mensaje técnico del último fallo
                                   pendiente de reintento (si vacío o
                                   ausente, no hay fallo pendiente).
"""
from __future__ import annotations
import os
import shutil
from datetime import datetime
from typing import List, Tuple, Optional

from db_manager import (
    get_db_path,
    metadata_get,
    metadata_set,
    metadata_delete,
    obtener_anios_para_archivar,
    mover_anio_a_archivo,
)


# ══════════════════════════════════════════════════════════════════════
#  Configuración
# ══════════════════════════════════════════════════════════════════════

# Cuántos años cerrados completos deben pasar antes de que un año sea
# candidato para archivar. Cesar decidió 5.
UMBRAL_ANIOS_ARCHIVO = 5

# Cuántos respaldos automáticos se mantienen. Cesar decidió 3.
# Los más viejos se eliminan al crear uno nuevo.
MAX_RESPALDOS_AUTOMATICOS = 3

# Prefijo del nombre de archivo para respaldos automáticos.
PREFIJO_RESPALDO = "respaldo_pre_archivo_"


# ══════════════════════════════════════════════════════════════════════
#  API pública
# ══════════════════════════════════════════════════════════════════════

def hay_migracion_pendiente() -> bool:
    """Devuelve True si al abrir CAMF hoy corresponde ejecutar la
    migración anual (todavía no se corrió este año, y hay años
    candidatos para archivar).

    Regla: se corre UNA vez por año calendario. Si ya se ejecutó en
    2028, no se vuelve a ejecutar hasta 2029 aunque el usuario abra
    y cierre CAMF 100 veces en 2028.
    """
    anio_actual = datetime.now().year
    ultima_str = metadata_get("ultima_migracion_archivo")

    if ultima_str is None:
        # Nunca se ha migrado. Solo tiene sentido si hay años elegibles.
        return len(obtener_anios_para_archivar(UMBRAL_ANIOS_ARCHIVO)) > 0

    try:
        ultima = int(ultima_str)
    except (ValueError, TypeError):
        # Metadata corrupta: tratamos como si nunca se hubiera migrado.
        return len(obtener_anios_para_archivar(UMBRAL_ANIOS_ARCHIVO)) > 0

    if ultima >= anio_actual:
        return False  # Ya se corrió este año.

    return len(obtener_anios_para_archivar(UMBRAL_ANIOS_ARCHIVO)) > 0


def hay_fallo_pendiente() -> bool:
    """Devuelve True si la última migración falló y el usuario aún no
    ha reintentado con éxito."""
    msg = metadata_get("notif_archivo_fallo_msg", "")
    return bool(msg)


def obtener_mensaje_fallo() -> str:
    """Mensaje técnico del último fallo, para mostrar al usuario cuando
    haga clic en la notificación de reintento."""
    return metadata_get("notif_archivo_fallo_msg", "") or ""


def ejecutar_migracion_anual() -> Tuple[bool, str]:
    """Ejecuta el ciclo completo de migración anual:

        1) Crear respaldo automático de seguridad.
        2) Rotar respaldos viejos (mantener MAX_RESPALDOS_AUTOMATICOS).
        3) Migrar cada año candidato (uno por uno, cada uno en su propia
           transacción atómica).
        4) Actualizar metadata:
             - Éxito → ultima_migracion_archivo = año actual;
               guardar flags para notificación de éxito.
             - Fallo → dejar ultima_migracion_archivo intacto; guardar
               mensaje de error para notificación de reintento.

    Retorna:
        (exito, mensaje)
          - exito=True   → la migración completó (o no había nada que hacer).
          - exito=False  → hubo un error; la BD quedó intacta.

    El mensaje contiene detalles útiles (cantidad archivada en éxito, o
    descripción del error en fallo). Es lo que la UI muestra al usuario.
    """
    anio_actual = datetime.now().year

    # Idempotencia: si ya se corrió este año, salir sin hacer nada.
    # PERO limpiando el flag de fallo si existiera — si el usuario está
    # reintentando desde la notificación de fallo y ahora ya no hay
    # migración pendiente, semánticamente el fallo ya no aplica. El
    # contrato de la función es: "si retorno True, no hay fallo pendiente".
    if not hay_migracion_pendiente():
        metadata_delete("notif_archivo_fallo_msg")
        return True, "No hay migración pendiente para este año."

    # ── Paso 1: respaldo automático ────────────────────────────────────
    ok_respaldo, msg_respaldo = crear_respaldo_automatico()
    if not ok_respaldo:
        # Sin respaldo, NO seguimos. Sería irresponsable migrar sin red.
        _marcar_fallo(f"No se pudo crear respaldo previo: {msg_respaldo}")
        return False, msg_respaldo

    # ── Paso 2: rotar respaldos viejos ─────────────────────────────────
    # No es crítico si falla — solo consume disco extra. Loguea y sigue.
    try:
        rotar_respaldos(MAX_RESPALDOS_AUTOMATICOS)
    except Exception as e:
        print(f"[migracion_archivo] rotación de respaldos falló (no bloqueante): {e}")

    # ── Paso 3: migrar cada año candidato ──────────────────────────────
    anios = obtener_anios_para_archivar(UMBRAL_ANIOS_ARCHIVO)
    total_movidos = 0
    anios_migrados: List[int] = []

    for anio in anios:
        exito, cantidad, err = mover_anio_a_archivo(anio)
        if not exito:
            # Un año falló → detener el proceso completo.
            _marcar_fallo(
                f"Falló al archivar el año {anio}: {err}. "
                f"Años ya migrados en esta ejecución: {anios_migrados or 'ninguno'}."
            )
            return False, err
        total_movidos += cantidad
        if cantidad > 0:
            anios_migrados.append(anio)

    # ── Paso 4: éxito — actualizar metadata ────────────────────────────
    metadata_set("ultima_migracion_archivo", str(anio_actual))
    # Limpiar cualquier fallo pendiente previo (por si el usuario reintentó
    # y ahora sí funcionó).
    metadata_delete("notif_archivo_fallo_msg")

    # Preparar flags de notificación de éxito.
    if total_movidos > 0:
        metadata_set("notif_archivo_exito_cantidad", str(total_movidos))
        metadata_set(
            "notif_archivo_exito_anio",
            ", ".join(str(a) for a in anios_migrados)
        )
        mensaje = (
            f"Se archivaron {total_movidos} mantenimientos "
            f"({', '.join(str(a) for a in anios_migrados)})."
        )
    else:
        # Se marcó como corrida en este año pero no había nada que mover.
        # No emitimos notificación de éxito para no molestar al usuario
        # con un aviso sin contenido informativo.
        mensaje = "No había años elegibles para archivar."

    return True, mensaje


def reintentar_migracion() -> Tuple[bool, str]:
    """Alias semántico de ejecutar_migracion_anual() usado cuando la
    llamada viene del clic del usuario en la notificación de fallo. La
    lógica es idéntica: intenta el proceso completo desde cero. Como
    los años ya archivados en un intento parcial anterior ya no aparecen
    en obtener_anios_para_archivar(), no se re-archivan.
    """
    return ejecutar_migracion_anual()


def marcar_notificacion_exito_leida() -> None:
    """Borra los flags de notificación de éxito. Llamado por inicio.py
    cuando el usuario marca la notificación como leída."""
    metadata_delete("notif_archivo_exito_cantidad")
    metadata_delete("notif_archivo_exito_anio")


# ══════════════════════════════════════════════════════════════════════
#  Respaldos automáticos
# ══════════════════════════════════════════════════════════════════════

def _carpeta_respaldos() -> str:
    """Ruta absoluta a %LOCALAPPDATA%\\CAMF\\respaldos_auto\\.
    Se crea si no existe."""
    db_path = get_db_path()
    if not db_path:
        return ""
    carpeta = os.path.join(os.path.dirname(db_path), "respaldos_auto")
    os.makedirs(carpeta, exist_ok=True)
    return carpeta


def crear_respaldo_automatico() -> Tuple[bool, str]:
    """Crea una copia del archivo memoria.db en la carpeta de respaldos
    automáticos, con nombre 'respaldo_pre_archivo_YYYY-MM-DD.db'.

    Retorna (exito, mensaje). El mensaje contiene la ruta del respaldo
    en éxito, o la descripción del error en fallo.
    """
    db_path = get_db_path()
    if not db_path or not os.path.exists(db_path):
        return False, "No se encontró el archivo de la base de datos."

    carpeta = _carpeta_respaldos()
    if not carpeta:
        return False, "No se pudo determinar la carpeta de respaldos."

    nombre = f"{PREFIJO_RESPALDO}{datetime.now().strftime('%Y-%m-%d')}.db"
    destino = os.path.join(carpeta, nombre)

    try:
        # copy2 preserva metadata del archivo (timestamps, permisos).
        shutil.copy2(db_path, destino)
        return True, destino
    except Exception as e:
        return False, f"No se pudo copiar la BD: {e}"


def rotar_respaldos(max_a_mantener: int = MAX_RESPALDOS_AUTOMATICOS) -> int:
    """Elimina respaldos automáticos viejos, dejando solo los N más
    recientes. Retorna la cantidad de respaldos eliminados.

    Ordena por fecha de modificación descendente (los más nuevos
    primero) y borra los que sobran.
    """
    carpeta = _carpeta_respaldos()
    if not carpeta or not os.path.exists(carpeta):
        return 0

    # Listar solo respaldos automáticos (por prefijo), no otros archivos
    # que el usuario pueda haber puesto ahí.
    respaldos = []
    for nombre in os.listdir(carpeta):
        if nombre.startswith(PREFIJO_RESPALDO) and nombre.endswith(".db"):
            ruta = os.path.join(carpeta, nombre)
            if os.path.isfile(ruta):
                respaldos.append((ruta, os.path.getmtime(ruta)))

    # Ordenar por fecha desc (más reciente primero).
    respaldos.sort(key=lambda x: x[1], reverse=True)

    # Borrar los que sobran (índices >= max_a_mantener).
    eliminados = 0
    for ruta, _ in respaldos[max_a_mantener:]:
        try:
            os.remove(ruta)
            eliminados += 1
        except Exception as e:
            print(f"[rotar_respaldos] no se pudo borrar {ruta}: {e}")

    return eliminados


def obtener_carpeta_respaldos_automaticos() -> Optional[str]:
    """Ruta a la carpeta de respaldos automáticos, para que el botón
    'Abrir carpeta de respaldos automáticos' de Configuración pueda
    invocarla con os.startfile() u os.system('explorer ...')."""
    carpeta = _carpeta_respaldos()
    return carpeta if carpeta and os.path.exists(carpeta) else None


# ══════════════════════════════════════════════════════════════════════
#  Helpers internos
# ══════════════════════════════════════════════════════════════════════

def _marcar_fallo(mensaje: str) -> None:
    """Guarda el mensaje de error en metadata_sistema para que la
    notificación de reintento en Inicio pueda dispararse."""
    metadata_set("notif_archivo_fallo_msg", mensaje)
    # Limpiar flags de éxito si existieran (contradictorio con fallo).
    metadata_delete("notif_archivo_exito_cantidad")
    metadata_delete("notif_archivo_exito_anio")
