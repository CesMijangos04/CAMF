# reportes_folios.py
"""
Emisión atómica de folios para reportes.

Un folio identifica de forma única e irrepetible un reporte emitido. Para
UVIE y auditoría esto es crítico: dos reportes nunca pueden compartir folio.

El patrón se configura por categoría en `reportes_folios_config` (sembrada
con seis patrones en la migración inicial). Soporta los tokens:
    {YYYY}   año actual (cuatro dígitos)
    {MM}     mes actual (dos dígitos)
    {####}   número consecutivo (cuatro dígitos, ceros a la izquierda)

Si la fila tiene `reset_anual=1` (default), el contador se reinicia
automáticamente cuando cambia de año.
"""

from datetime import datetime
from typing import Optional

from db_manager import connect_db


# ── API pública ─────────────────────────────────────────────────────────────

def emitir_folio(categoria: str, fecha: Optional[datetime] = None) -> str:
    """
    Emite un nuevo folio para la categoría dada.

    Operación atómica: lee el contador actual, formatea el folio con ese
    número, incrementa el contador y aplica reset anual si corresponde —
    todo dentro de una transacción EXCLUSIVE para evitar carreras entre
    emisiones simultáneas.

    Args:
        categoria: Una de 'operativos' | 'tecnicos' | 'ingenieria' |
                   'uvie' | 'gestion' | 'inventario'.
        fecha:     Marca temporal del folio. Si es None, usa now().

    Returns:
        El folio formateado, ej. 'CAMF-OP-2026-0001'.

    Raises:
        ValueError:   La categoría no existe.
        RuntimeError: No se pudo conectar a la BD.
    """
    if fecha is None:
        fecha = datetime.now()

    conn = connect_db()
    if conn is None:
        raise RuntimeError("No se pudo conectar a la base de datos.")

    try:
        cur = conn.cursor()
        cur.execute("BEGIN EXCLUSIVE")

        row = cur.execute("""
            SELECT id, patron, siguiente_numero, anio_actual, reset_anual
            FROM reportes_folios_config
            WHERE categoria = ?
        """, (categoria,)).fetchone()

        if not row:
            conn.rollback()
            raise ValueError(f"Categoría desconocida: '{categoria}'")

        folio_id, patron, numero, anio_actual, reset_anual = row

        # Reset anual si el año cambió y el patrón lo soporta
        if reset_anual and anio_actual != fecha.year:
            numero = 1
            anio_actual = fecha.year

        folio = formatear_folio(patron, numero, fecha)

        # Incrementar para la próxima emisión
        cur.execute("""
            UPDATE reportes_folios_config
            SET siguiente_numero = ?, anio_actual = ?
            WHERE id = ?
        """, (numero + 1, anio_actual, folio_id))
        conn.commit()
        return folio
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def formatear_folio(patron: str, numero: int, fecha: Optional[datetime] = None) -> str:
    """
    Sustituye los tokens del patrón con valores reales.

    Tokens soportados:
        {YYYY}, {MM}, {####}

    No incrementa el contador — esto es solo formateo, útil para previews.
    """
    if fecha is None:
        fecha = datetime.now()
    return (patron
            .replace('{YYYY}', str(fecha.year))
            .replace('{MM}',   f"{fecha.month:02d}")
            .replace('{####}', f"{numero:04d}"))


def previsualizar_proximo_folio(categoria: str) -> str:
    """
    Devuelve cómo se verá el próximo folio sin emitirlo (no incrementa).

    Útil para mostrar al usuario "el siguiente folio será X" antes de
    confirmar la generación del reporte.
    """
    conn = connect_db()
    if conn is None:
        return ""
    try:
        row = conn.execute("""
            SELECT patron, siguiente_numero, anio_actual, reset_anual
            FROM reportes_folios_config
            WHERE categoria = ?
        """, (categoria,)).fetchone()
        if not row:
            return ""
        patron, numero, anio_actual, reset_anual = row
        ahora = datetime.now()
        if reset_anual and anio_actual != ahora.year:
            numero = 1
        return formatear_folio(patron, numero, ahora)
    finally:
        conn.close()
