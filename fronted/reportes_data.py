# reportes_data.py
"""
Capa de datos del módulo de reportes.

Una función por cada `tipo_reporte`. Cada función recibe parámetros del
reporte (rango de fechas, equipo seleccionado, etc.) y devuelve un dict
estandarizado que la capa de render (reportes_render.py) sabe consumir.

Esta separación es la que permite agregar reportes nuevos sin tocar el
motor: solo se agrega una función nueva aquí y un nuevo `if` en el
dispatcher de `reportes_render.emitir_reporte`.

Contrato del dict devuelto (mínimo):
    {
        'titulo':        str,
        'subtitulo':     str (opcional),
        'rango_fechas':  {'desde': str|None, 'hasta': str|None},
        # ...campos específicos de cada tipo
    }
"""

from datetime import datetime
from typing import Optional, Dict, Any, List

from db_manager import connect_db


# ══════════════════════════════════════════════════════════════════════════
#  REPORTE 1.1 — Historial de mantenimiento por equipo
# ══════════════════════════════════════════════════════════════════════════

def historial_mantenimiento_por_equipo(
    equipo_id: str,
    equipo_tipo: str,
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Devuelve todos los datos del reporte "Historial de mantenimiento" para
    un equipo dado.

    Args:
        equipo_id:   ID textual del equipo (la PK de tableros/transformadores,
                     ej. 'TG-01', 'TR-A1' — definido por el usuario).
        equipo_tipo: 'tableros' | 'transformadores' (igual que el campo
                     en mantenimientos_equipos.equipo_tipo).
        fecha_inicio: ISO 'YYYY-MM-DD' (opcional, default = todos).
        fecha_fin:    ISO 'YYYY-MM-DD' (opcional, default = todos).

    Returns:
        Dict con: titulo, subtitulo, equipo, rango_fechas, mantenimientos,
                  resumen.
    """
    base = {
        'titulo':       'Historial de mantenimiento',
        'subtitulo':    '',
        'equipo':       {},
        'rango_fechas': {'desde': fecha_inicio, 'hasta': fecha_fin},
        'mantenimientos': [],
        'resumen':      {},
    }

    conn = connect_db()
    if conn is None:
        return base

    try:
        cur = conn.cursor()

        # ── Datos del equipo ─────────────────────────────────────────────
        equipo = _cargar_equipo(cur, equipo_id, equipo_tipo)
        if not equipo:
            return base
        base['equipo'] = equipo
        base['subtitulo'] = f"{equipo['tipo_equipo']} · {equipo['identificador']}"

        # ── Eventos de mantenimiento ─────────────────────────────────────
        params: List[Any] = [equipo_tipo, equipo_id]
        where_extra = ""
        if fecha_inicio:
            where_extra += " AND m.fecha_inicio >= ?"
            params.append(fecha_inicio)
        if fecha_fin:
            where_extra += " AND m.fecha_inicio <= ?"
            params.append(fecha_fin)

        cur.execute(f"""
            SELECT
                m.id, m.fecha_inicio, m.fecha_fin, m.fecha_cierre,
                m.tipo_mantenimiento, m.estado, m.urgente,
                m.descripcion, m.retroalimentacion,
                m.responsable_nombre,
                m.costo, m.costo_moneda,
                m.costo_real, m.costo_real_moneda
            FROM mantenimientos m
            JOIN mantenimientos_equipos me ON me.mantenimiento_id = m.id
            WHERE me.equipo_tipo = ? AND me.equipo_id = ?
              AND LOWER(m.estado) IN ('finalizado', 'cancelado')
            {where_extra}
            ORDER BY m.fecha_inicio DESC
        """, params)

        mantenimientos: List[Dict[str, Any]] = []
        for r in cur.fetchall():
            mantenimientos.append({
                'id':                 r[0],
                'fecha_inicio':       r[1],
                'fecha_fin':          r[2],
                'fecha_cierre':       r[3],
                'tipo':               r[4],
                'estado':             r[5],
                'urgente':            bool(r[6]) if r[6] is not None else False,
                'descripcion':        r[7] or '',
                'retroalimentacion':  r[8] or '',
                'responsable':        r[9] or '',
                'costo':              float(r[10]) if r[10] is not None else 0.0,
                'costo_moneda':       r[11] or 'MXN',
                'costo_real':         float(r[12]) if r[12] is not None else 0.0,
                'costo_real_moneda':  r[13] or 'MXN',
            })

        base['mantenimientos'] = mantenimientos
        base['resumen'] = _calcular_resumen_mantenimientos(mantenimientos)
        return base
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════
#  Helpers privados
# ══════════════════════════════════════════════════════════════════════════

def _cargar_equipo(cur, equipo_id: str, equipo_tipo: str) -> Optional[Dict[str, Any]]:
    """
    Devuelve un dict uniforme con los datos del equipo, o None si no existe.

    Nota: equipo_id es TEXT (la PK que el usuario asigna, ej. 'TG-01'). Tanto
    tableros como transformadores usan TEXT como PK.
    """
    if equipo_tipo == 'tableros':
        cur.execute("""
            SELECT id, nombre, ubicacion, corriente_nominal, tension, tipo,
                   num_circuitos, marca, fecha_instalacion
            FROM tableros WHERE id = ?
        """, (equipo_id,))
        r = cur.fetchone()
        if not r:
            return None
        return {
            'identificador':      r[0],            # el id ya es el identificador
            'nombre':             r[1] or '',
            'tipo_equipo':        'Tablero',
            'ubicacion':          r[2] or '',
            'datos_tecnicos': [
                ('Tipo',                 r[5] or '—'),
                ('Marca',                r[7] or '—'),
                ('Tensión',              f"{r[4]} V"  if r[4] else '—'),
                ('Corriente nominal',    f"{r[3]} A"  if r[3] else '—'),
                ('Número de circuitos',  str(r[6])    if r[6] is not None else '—'),
                ('Fecha de instalación', r[8] or '—'),
            ],
        }

    if equipo_tipo == 'transformadores':
        cur.execute("""
            SELECT id, ubicacion, capacidad, tension, marca, enfriamiento,
                   fases, conexion, tipo, fecha
            FROM transformadores WHERE id = ?
        """, (equipo_id,))
        r = cur.fetchone()
        if not r:
            return None
        return {
            'identificador': r[0],
            'nombre':        '',
            'tipo_equipo':   'Transformador',
            'ubicacion':     r[1] or '',
            'datos_tecnicos': [
                ('Tipo',         r[8] or '—'),
                ('Marca',        r[4] or '—'),
                ('Capacidad',    f"{r[2]} kVA" if r[2] else '—'),
                ('Tensión',      r[3] or '—'),
                ('Conexión',     r[7] or '—'),
                ('Fases',        str(r[6])     if r[6] is not None else '—'),
                ('Enfriamiento', r[5] or '—'),
                ('Fecha',        r[9] or '—'),
            ],
        }

    return None


def _calcular_resumen_mantenimientos(mantenimientos: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calcula estadísticas agregadas de la lista de mantenimientos."""
    if not mantenimientos:
        return {
            'total_eventos':  0,
            'finalizados':    0,
            'cancelados':     0,
            'preventivos':    0,
            'correctivos':    0,
            'costo_total':    0.0,
            'costo_moneda':   'MXN',
        }

    total = len(mantenimientos)
    finalizados = sum(1 for m in mantenimientos
                      if (m['estado'] or '').lower() == 'finalizado')
    cancelados  = sum(1 for m in mantenimientos
                      if (m['estado'] or '').lower() == 'cancelado')
    preventivos = sum(1 for m in mantenimientos
                      if 'preventivo' in (m['tipo'] or '').lower())
    correctivos = sum(1 for m in mantenimientos
                      if 'correctivo' in (m['tipo'] or '').lower())

    # Costo total: prefiere costo_real si existe, si no usa costo planeado
    costo_total = sum(
        (m['costo_real'] if m['costo_real'] else m['costo']) or 0.0
        for m in mantenimientos
    )

    # Moneda dominante (asumimos consistencia; si hay mezcla, marca primero)
    moneda = mantenimientos[0]['costo_real_moneda'] or mantenimientos[0]['costo_moneda'] or 'MXN'

    return {
        'total_eventos': total,
        'finalizados':   finalizados,
        'cancelados':    cancelados,
        'preventivos':   preventivos,
        'correctivos':   correctivos,
        'costo_total':   costo_total,
        'costo_moneda':  moneda,
    }


# ══════════════════════════════════════════════════════════════════════════
#  REPORTE 1.1 — Historial de mantenimiento (multi-equipo)
# ══════════════════════════════════════════════════════════════════════════

def historial_mantenimiento_por_equipos(
    equipos: List[Dict[str, str]],
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Versión multi-equipo del reporte "Historial de mantenimiento".

    Args:
        equipos: lista de dicts con al menos {'id', 'tipo'}. El 'tipo' debe
                 ser 'tableros' o 'transformadores'. Acepta también el
                 formato {'id', 'tipo', 'ubicacion'} que devuelve
                 SelectorEquipoDialog.
        fecha_inicio: ISO 'YYYY-MM-DD' (opcional, default = todos).
        fecha_fin:    ISO 'YYYY-MM-DD' (opcional, default = todos).

    Returns:
        Dict con:
          - titulo:        'Historial de mantenimiento'
          - subtitulo:     resumen de la selección
          - rango_fechas:  {'desde', 'hasta'}
          - secciones:     lista, una entrada por equipo, cada una con
                           {'equipo', 'mantenimientos', 'resumen'}
          - resumen_global: stats acumuladas de todos los equipos
          - n_equipos:     int
    """
    base: Dict[str, Any] = {
        'titulo':         'Historial de mantenimiento',
        'subtitulo':      '',
        'rango_fechas':   {'desde': fecha_inicio, 'hasta': fecha_fin},
        'secciones':      [],
        'resumen_global': {},
        'n_equipos':      len(equipos),
    }

    if not equipos:
        return base

    # Recolectar datos por equipo reutilizando la función single-equipo
    for eq in equipos:
        datos_eq = historial_mantenimiento_por_equipo(
            equipo_id    = eq['id'],
            equipo_tipo  = eq['tipo'],
            fecha_inicio = fecha_inicio,
            fecha_fin    = fecha_fin,
        )
        # Si el equipo no existe en BD (raro pero posible si fue borrado
        # entre la selección y la generación), saltamos.
        if not datos_eq.get('equipo'):
            continue
        base['secciones'].append({
            'equipo':         datos_eq['equipo'],
            'mantenimientos': datos_eq['mantenimientos'],
            'resumen':        datos_eq['resumen'],
        })

    # Subtítulo descriptivo
    n = len(base['secciones'])
    if n == 1:
        eq = base['secciones'][0]['equipo']
        base['subtitulo'] = f"{eq['tipo_equipo']} · {eq['identificador']}"
    elif n > 1:
        # Si todos los equipos comparten el mismo grupo, usamos el path
        # del grupo como subtítulo. Si la selección es mixta, fallback
        # al conteo.
        path_grupo = _ruta_grupo_comun(equipos)
        if path_grupo:
            base['subtitulo'] = f"{path_grupo} · {n} equipos"
        else:
            base['subtitulo'] = f"{n} equipos seleccionados"

    # Resumen global = suma de los individuales
    base['resumen_global'] = _resumen_global([s['resumen'] for s in base['secciones']])
    return base


def _ruta_grupo_comun(equipos: List[Dict[str, str]]) -> Optional[str]:
    """
    Si todos los equipos seleccionados comparten el mismo `grupo_id`
    (y ese grupo_id no es NULL), devuelve la ruta del grupo en formato
    'Empresa / Edificio / Sala'.
    Si la selección abarca varios grupos o equipos sin grupo, devuelve None.
    """
    if not equipos:
        return None

    conn = connect_db()
    if conn is None:
        return None
    try:
        cur = conn.cursor()
        grupo_ids: set = set()
        for eq in equipos:
            tabla = eq.get('tipo')
            if tabla not in ('tableros', 'transformadores'):
                return None
            cur.execute(f"SELECT grupo_id FROM {tabla} WHERE id = ?", (eq['id'],))
            r = cur.fetchone()
            if r is None:
                # Equipo no existe en BD: no hay grupo común útil
                return None
            grupo_ids.add(r[0])

        # Solo procedemos si todos tienen el mismo grupo_id y no es NULL
        if len(grupo_ids) != 1:
            return None
        grupo_id = next(iter(grupo_ids))
        if grupo_id is None:
            return None

        # Construir el path subiendo por padre_id
        return _construir_ruta_grupo(cur, grupo_id)
    finally:
        conn.close()


def _construir_ruta_grupo(cur, grupo_id: int) -> Optional[str]:
    """
    Devuelve la ruta jerárquica de un grupo en formato 'A / B / C'.
    Ejemplo: si grupo_id apunta a 'Sala A' cuyo padre es 'Edificio K' cuyo
    padre es 'Bimbo', devuelve 'Bimbo / Edificio K / Sala A'.
    """
    partes: List[str] = []
    actual: Optional[int] = grupo_id
    visitados: set = set()  # protección anti-ciclo
    while actual is not None and actual not in visitados:
        visitados.add(actual)
        cur.execute("SELECT nombre, padre_id FROM grupos WHERE id = ?", (actual,))
        r = cur.fetchone()
        if not r:
            break
        nombre, padre_id = r[0], r[1]
        partes.insert(0, nombre or '')
        actual = padre_id
    # Limpiar nombres vacíos
    partes = [p for p in partes if p]
    return " / ".join(partes) if partes else None


def _resumen_global(resumenes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Suma los contadores y costos de N resúmenes individuales."""
    if not resumenes:
        return {
            'total_eventos': 0, 'finalizados': 0, 'cancelados': 0,
            'preventivos':   0, 'correctivos': 0,
            'costo_total':   0.0, 'costo_moneda': 'MXN',
        }
    total = sum(r['total_eventos'] for r in resumenes)
    fin   = sum(r['finalizados']   for r in resumenes)
    can   = sum(r['cancelados']    for r in resumenes)
    pre   = sum(r['preventivos']   for r in resumenes)
    cor   = sum(r['correctivos']   for r in resumenes)
    cost  = sum(r['costo_total']   for r in resumenes)
    moneda = next((r['costo_moneda'] for r in resumenes if r['costo_moneda']), 'MXN')
    return {
        'total_eventos': total,
        'finalizados':   fin,
        'cancelados':    can,
        'preventivos':   pre,
        'correctivos':   cor,
        'costo_total':   cost,
        'costo_moneda':  moneda,
    }
