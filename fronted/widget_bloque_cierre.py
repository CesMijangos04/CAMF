"""
Widget de bloque de cierre — secciones específicas por tipo de equipo.

Este módulo se llama desde `ficha_mantenimiento.py::_bloque_cierre` para
pintar el contenido específico según el tipo de mantenimiento cerrado:

  - Para tableros: sección "CAMBIOS AL EQUIPO" con las modificaciones que
    se aplicaron durante el cierre (tachado + flecha verde + justificación).
  - Para transformadores: 3 secciones con los datos capturados: PRUEBAS
    ELÉCTRICAS (con veredictos normativos aplicados por el motor
    `evaluar_prueba`), INSPECCIÓN FÍSICA, y POSICIÓN DEL TAP.

Es AUTOCONTENIDO: los imports pesados (db_manager, evaluacion_transformador)
se hacen lazy dentro de las funciones para no acoplar la importación de este
módulo al arranque de la app.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFrame,
)


# ── Paleta de veredictos ────────────────────────────────────────────────
# Colores usados para pintar los chips de veredicto normativo y de estado
# de inspección. Se replican como constantes locales para mantener el
# módulo autocontenido (misma convención que otros widgets del proyecto).
_COLOR_APROBADA = "#5DCAA5"   # verde suave
_COLOR_ATENCION = "#EF9F27"   # ámbar
_COLOR_FALLA    = "#e84747"   # rojo
_COLOR_NEUTRAL  = "#7a7a7a"   # gris (para 'no aplica' / 'no ejecutada')

# Mapeo de código de estado (de BD) a display + color
_CHIP_INSPECCION = {
    "ok":          ("OK",         _COLOR_APROBADA),
    "atencion":    ("Atención",   _COLOR_ATENCION),
    "falla":       ("Falla",      _COLOR_FALLA),
    "na":          ("N/A",        _COLOR_NEUTRAL),
    "no_revisado": ("No revisado", _COLOR_NEUTRAL),
}

_CHIP_VEREDICTO = {
    "aprobada":     ("Aprobada",     _COLOR_APROBADA),
    "atencion":     ("Atención",     _COLOR_ATENCION),
    "falla":        ("Falla",        _COLOR_FALLA),
    "no_ejecutada": ("No ejecutada", _COLOR_NEUTRAL),
}


# ─── Sección compartida: título de sección ─────────────────────────────
def _agregar_titulo_seccion(parent_lay: QVBoxLayout, texto: str,
                            sub: str = None):
    """
    Agrega una fila de título estilo mockup ("CAMBIOS AL EQUIPO", con
    letra pequeña gris claro y letter-spacing).
    """
    row = QHBoxLayout()
    row.setContentsMargins(0, 6, 0, 2)
    row.setSpacing(6)

    lbl = QLabel(texto)
    lbl.setStyleSheet(
        "color: #666; font-size: 11px; letter-spacing: 1px; "
        "font-weight: 500; background: transparent;"
    )
    row.addWidget(lbl)

    if sub:
        s = QLabel(f"· {sub}")
        s.setStyleSheet(
            "color: #555; font-size: 10.5px; font-style: italic; "
            "background: transparent;"
        )
        row.addWidget(s)

    row.addStretch()
    parent_lay.addLayout(row)


def _chip(texto: str, color: str) -> QLabel:
    """Crea un chip pequeño de estado/veredicto con color de fondo suave."""
    lbl = QLabel(texto)
    # Fondo con opacidad 15% del color; texto con el color pleno
    lbl.setStyleSheet(
        f"color: {color}; background: {color}22; "
        "border-radius: 4px; padding: 2px 8px; "
        "font-size: 11px; font-weight: 500;"
    )
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return lbl


# ═══════════════════════════════════════════════════════════════════════
#  Render de CAMBIOS AL EQUIPO (tableros)
# ═══════════════════════════════════════════════════════════════════════
def render_cambios_tablero(parent_lay: QVBoxLayout, mant_id: int):
    """
    Pinta la sección "CAMBIOS AL EQUIPO" en el bloque de cierre.

    Consume `obtener_cambios_equipo(mant_id)` (con fallback automático a
    archivo histórico si el mantenimiento está archivado). Agrupa por
    tablero y por circuito. Solo se muestran circuitos que efectivamente
    tuvieron cambios; los que no cambiaron NO se listan (sus valores
    actuales pueden haber sido modificados por mantenimientos posteriores,
    mostrarlos como "sin cambios" sería engañoso históricamente).

    Si el mantenimiento no aplicó ningún cambio, la sección no se pinta
    en absoluto (silencio informativo).
    """
    try:
        from db_manager import obtener_cambios_equipo
    except Exception as e:
        print(f"[bloque_cierre] No se pudo importar obtener_cambios_equipo: {e}")
        return

    cambios = obtener_cambios_equipo(mant_id)
    if not cambios:
        return  # sin cambios → sin sección

    _agregar_titulo_seccion(parent_lay, "CAMBIOS AL EQUIPO")

    # Agrupar por tablero → circuito → lista de cambios
    por_tablero = {}
    for c in cambios:
        tid = c.get("tablero_id") or "(sin tablero)"
        cid = c.get("equipo_id")
        por_tablero.setdefault(tid, {}).setdefault(cid, []).append(c)

    # Un card por tablero
    for tablero_id, circuitos in por_tablero.items():
        card = QFrame()
        card.setObjectName("card_tablero_cierre")
        card.setStyleSheet(
            "QFrame#card_tablero_cierre { "
            "background: rgba(255,255,255,0.02); border-radius: 6px; "
            "padding: 8px; }"
            "QFrame#card_tablero_cierre QLabel { background: transparent; }"
        )
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(10, 8, 10, 8)
        card_lay.setSpacing(4)

        # Header del tablero: id + conteo
        hdr = QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 2)
        lbl_tid = QLabel(tablero_id)
        lbl_tid.setStyleSheet(
            f"color: {_COLOR_ATENCION}; font-family: 'Consolas', monospace; "
            "font-size: 12.5px; font-weight: 500;"
        )
        hdr.addWidget(lbl_tid)
        hdr.addStretch()
        n_circ = len(circuitos)
        lbl_n = QLabel(
            f"{n_circ} circuito{'s' if n_circ != 1 else ''} modificado"
            f"{'s' if n_circ != 1 else ''}"
        )
        lbl_n.setStyleSheet("color: #888; font-size: 11px;")
        hdr.addWidget(lbl_n)
        card_lay.addLayout(hdr)

        # Un bloque por circuito
        for cid, filas in circuitos.items():
            _render_circuito_cambiado(card_lay, cid, filas)

        parent_lay.addWidget(card)


def _render_circuito_cambiado(parent_lay: QVBoxLayout, cid: str, filas: list):
    """
    Pinta un circuito con sus cambios. Cada `campo` modificado se muestra
    como una fila con formato:  C-XX  campo  valor_anterior → valor_nuevo
    Y debajo de todas las filas de ese circuito, la justificación (que es
    la misma para todos los campos del mismo circuito modificado en el
    mismo cierre).
    """
    contenedor = QWidget()
    contenedor.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    v = QVBoxLayout(contenedor)
    v.setContentsMargins(0, 4, 0, 2)
    v.setSpacing(2)

    # Cabecera del circuito
    lbl_id = QLabel(f"C-{cid}")
    lbl_id.setStyleSheet(
        f"color: {_COLOR_ATENCION}; font-family: 'Consolas', monospace; "
        "font-size: 11.5px; font-weight: 500; background: transparent;"
    )
    v.addWidget(lbl_id)

    # Una fila por campo modificado
    for f in filas:
        campo = f.get("campo", "")
        val_ant = f.get("valor_anterior") or "—"
        val_nue = f.get("valor_nuevo") or "—"

        row = QHBoxLayout()
        row.setContentsMargins(16, 0, 0, 0)
        row.setSpacing(6)

        lbl_campo = QLabel(_nombre_campo_display(campo))
        lbl_campo.setStyleSheet(
            "color: #999; font-size: 11.5px; background: transparent;"
        )
        lbl_campo.setFixedWidth(120)
        row.addWidget(lbl_campo)

        # Valor anterior tachado
        lbl_ant = QLabel(str(val_ant))
        lbl_ant.setStyleSheet(
            "color: #666; font-family: 'Consolas', monospace; "
            "font-size: 12px; text-decoration: line-through; "
            "background: transparent;"
        )
        row.addWidget(lbl_ant)

        # Flecha
        lbl_flecha = QLabel("→")
        lbl_flecha.setStyleSheet(
            f"color: {_COLOR_APROBADA}; font-size: 12px; background: transparent;"
        )
        row.addWidget(lbl_flecha)

        # Valor nuevo en verde
        lbl_nue = QLabel(str(val_nue))
        lbl_nue.setStyleSheet(
            f"color: {_COLOR_APROBADA}; font-family: 'Consolas', monospace; "
            "font-size: 12px; font-weight: 500; background: transparent;"
        )
        row.addWidget(lbl_nue)
        row.addStretch()
        v.addLayout(row)

    # Justificación (una sola, común a todos los campos del circuito)
    justif = filas[0].get("justificacion", "").strip() if filas else ""
    if justif:
        lbl_just = QLabel(f"Justificación: {justif}")
        lbl_just.setStyleSheet(
            f"color: {_COLOR_ATENCION}; font-size: 11.5px; "
            "background: transparent; padding: 4px 16px 0 16px; font-style: italic;"
        )
        lbl_just.setWordWrap(True)
        v.addWidget(lbl_just)

    parent_lay.addWidget(contenedor)


def _nombre_campo_display(campo: str) -> str:
    """Traduce el nombre de columna de BD a un nombre humano para el reporte."""
    m = {
        "calibre_fase":     "Calibre de fase",
        "calibre_neutro":   "Calibre de neutro",
        "calibre_tierra":   "Calibre de tierra",
        "material":         "Material",
        "amperaje_a":       "ITM (A)",
        "capacidad_int_ka": "Capacidad kA",
        "aislamiento":      "Aislamiento",
        "tuberia_mm":       "Tubería (mm)",
        "observaciones":    "Observaciones",
    }
    return m.get(campo, campo)


# ═══════════════════════════════════════════════════════════════════════
#  Render de PRUEBAS DEL TRANSFORMADOR
# ═══════════════════════════════════════════════════════════════════════
def render_pruebas_transformador(parent_lay: QVBoxLayout, mant_id: int):
    """
    Pinta las 3 secciones específicas del cierre de un mantenimiento de
    transformador:
        - PRUEBAS ELÉCTRICAS / AL ACEITE (con veredictos normativos
          calculados por `evaluar_prueba` — aprobada / atención / falla)
        - INSPECCIÓN FÍSICA (chips coloreados por estado capturado)
        - POSICIÓN DEL TAP (antes → después con justificación)

    Cada sección se pinta solo si tiene datos. Sin datos, silencio.
    """
    try:
        from db_manager import (
            obtener_pruebas_transformador,
            obtener_inspeccion_transformador,
            obtener_posicion_tap,
        )
        from evaluacion_transformador import evaluar_prueba, obtener_metadata
    except Exception as e:
        print(f"[bloque_cierre] Fallo al importar dependencias: {e}")
        return

    pruebas = obtener_pruebas_transformador(mant_id)
    inspeccion = obtener_inspeccion_transformador(mant_id)
    taps = obtener_posicion_tap(mant_id)

    # ── Sección PRUEBAS ────────────────────────────────────────────────
    if pruebas:
        # Separar pruebas eléctricas vs al aceite según su código.
        # Las de aceite son: rigidez_aceite_kv, humedad_aceite_ppm,
        # acidez_aceite_koh. El resto son eléctricas comunes.
        codigos_aceite = {
            "rigidez_aceite_kv", "humedad_aceite_ppm", "acidez_aceite_koh",
        }
        electricas = [p for p in pruebas if p["prueba_codigo"] not in codigos_aceite]
        aceite     = [p for p in pruebas if p["prueba_codigo"] in codigos_aceite]

        if electricas:
            _agregar_titulo_seccion(parent_lay, "PRUEBAS ELÉCTRICAS")
            for p in electricas:
                _render_prueba(parent_lay, p, evaluar_prueba, obtener_metadata)

        if aceite:
            _agregar_titulo_seccion(
                parent_lay, "PRUEBAS AL ACEITE",
                sub="transformador sumergido"
            )
            for p in aceite:
                _render_prueba(parent_lay, p, evaluar_prueba, obtener_metadata)

    # ── Sección INSPECCIÓN FÍSICA ───────────────────────────────────────
    if inspeccion:
        _agregar_titulo_seccion(parent_lay, "INSPECCIÓN FÍSICA")
        _render_grid_inspeccion(parent_lay, inspeccion)

    # ── Sección POSICIÓN DEL TAP ────────────────────────────────────────
    if taps:
        _agregar_titulo_seccion(
            parent_lay, "POSICIÓN DEL CAMBIADOR DE DERIVACIONES (TAP)"
        )
        for t in taps:
            _render_tap(parent_lay, t)


def _render_prueba(parent_lay: QVBoxLayout, p: dict,
                   evaluar_prueba, obtener_metadata):
    """
    Pinta una prueba: [nombre]   [valor + unidad]   [chip veredicto]
    Debajo de la fila, si hay recomendación, aparece con formato itálico.
    """
    codigo = p.get("prueba_codigo", "")
    valor  = p.get("valor")
    estado_bd = p.get("estado", "")
    unidad = p.get("unidad") or ""

    meta = obtener_metadata(codigo)
    nombre = (meta["nombre"] if meta else codigo)

    # Aplicar motor de veredicto. Si el ingeniero marcó "no ejecutada",
    # ese es el veredicto directo (no aplica el motor).
    if estado_bd == "no_ejecutada":
        veredicto = "no_ejecutada"
        norma = meta["norma"] if meta else ""
        recomendacion = None
    else:
        r = evaluar_prueba(codigo, valor)
        veredicto = r["veredicto"]
        norma = r["norma"]
        recomendacion = r["recomendacion"]

    contenedor = QWidget()
    contenedor.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    v = QVBoxLayout(contenedor)
    v.setContentsMargins(0, 3, 0, 3)
    v.setSpacing(2)

    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)

    # Nombre de la prueba
    lbl_nombre = QLabel(nombre)
    lbl_nombre.setStyleSheet(
        "color: #ccc; font-size: 12px; background: transparent;"
    )
    lbl_nombre.setWordWrap(True)
    lbl_nombre.setMinimumWidth(240)
    row.addWidget(lbl_nombre, 1)

    # Valor + unidad
    if valor is not None:
        if isinstance(valor, float) and valor == int(valor):
            val_txt = f"{int(valor)}"
        else:
            val_txt = f"{valor}"
        if unidad:
            val_txt = f"{val_txt} {unidad}"
    else:
        val_txt = "—"
    lbl_valor = QLabel(val_txt)
    lbl_valor.setStyleSheet(
        "color: #ccc; font-family: 'Consolas', monospace; "
        "font-size: 12px; background: transparent;"
    )
    lbl_valor.setMinimumWidth(120)
    row.addWidget(lbl_valor)

    # Chip veredicto (con norma como tooltip)
    label, color = _CHIP_VEREDICTO.get(veredicto, (veredicto, _COLOR_NEUTRAL))
    chip = _chip(label, color)
    if norma:
        chip.setToolTip(norma)
    row.addWidget(chip)

    v.addLayout(row)

    # Observación capturada (si existe)
    obs = (p.get("observacion") or "").strip()
    if obs:
        lbl_obs = QLabel(f"Nota: {obs}")
        lbl_obs.setStyleSheet(
            "color: #888; font-size: 11px; padding: 0 0 0 8px; "
            "background: transparent; font-style: italic;"
        )
        lbl_obs.setWordWrap(True)
        v.addWidget(lbl_obs)

    # Recomendación del motor (atención/falla)
    if recomendacion:
        lbl_rec = QLabel(f"Recomendación: {recomendacion}")
        lbl_rec.setStyleSheet(
            f"color: {_COLOR_ATENCION}; font-size: 11px; "
            "padding: 0 0 0 8px; background: transparent; font-style: italic;"
        )
        lbl_rec.setWordWrap(True)
        v.addWidget(lbl_rec)

    parent_lay.addWidget(contenedor)


def _render_grid_inspeccion(parent_lay: QVBoxLayout, inspeccion: list):
    """
    Pinta la inspección física como grid de 2 columnas con chip coloreado
    por punto — la forma que aprobamos en el mockup original.
    """
    grid = QGridLayout()
    grid.setContentsMargins(0, 2, 0, 2)
    grid.setHorizontalSpacing(20)
    grid.setVerticalSpacing(6)

    for i, item in enumerate(inspeccion):
        punto = item.get("punto", "")
        estado = item.get("estado", "")
        observacion = (item.get("observacion") or "").strip()

        cell = QWidget()
        cell.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        cell_lay = QHBoxLayout(cell)
        cell_lay.setContentsMargins(0, 0, 0, 0)
        cell_lay.setSpacing(6)

        lbl_nombre = QLabel(_nombre_punto_display(punto))
        lbl_nombre.setStyleSheet(
            "color: #ccc; font-size: 12px; background: transparent;"
        )
        cell_lay.addWidget(lbl_nombre, 1)

        label, color = _CHIP_INSPECCION.get(estado, (estado, _COLOR_NEUTRAL))
        chip = _chip(label, color)
        if observacion:
            chip.setToolTip(observacion)
        cell_lay.addWidget(chip)

        row = i // 2
        col = i % 2
        grid.addWidget(cell, row, col)

    parent_lay.addLayout(grid)


def _nombre_punto_display(punto: str) -> str:
    """Traduce el código de punto de inspección al nombre para el reporte."""
    m = {
        "bushings_at":        "Bushings de alta tensión",
        "bushings_bt":        "Bushings de baja tensión",
        "aterrizaje":         "Sistema de aterrizaje",
        "apriete_conexiones": "Apriete de conexiones",
        "gabinete":           "Gabinete · limpieza",
        "nivel_aceite":       "Nivel de aceite",
        "silica_gel":         "Silica gel",
        "tanque":             "Tanque · fugas",
        "radiadores":         "Radiadores",
        "protecciones":       "Protecciones (Buchholz)",
    }
    return m.get(punto, punto.replace("_", " ").capitalize())


def _render_tap(parent_lay: QVBoxLayout, t: dict):
    """
    Pinta un ajuste de tap: [Posición]  [antes] → [después]  [chip]
    Con justificación debajo si los valores difieren.
    """
    antes = t.get("posicion_antes")
    despues = t.get("posicion_despues")
    justif = (t.get("justificacion") or "").strip()
    difieren = antes != despues

    contenedor = QWidget()
    contenedor.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    v = QVBoxLayout(contenedor)
    v.setContentsMargins(0, 3, 0, 3)
    v.setSpacing(2)

    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(10)

    lbl_pos = QLabel("Posición del tap")
    lbl_pos.setStyleSheet("color: #ccc; font-size: 12px; background: transparent;")
    row.addWidget(lbl_pos, 1)

    lbl_antes = QLabel(str(antes))
    lbl_antes.setStyleSheet(
        "color: #999; font-family: 'Consolas', monospace; "
        "font-size: 12px; background: transparent;"
    )
    row.addWidget(lbl_antes)

    lbl_arrow = QLabel("→")
    lbl_arrow.setStyleSheet(
        f"color: {_COLOR_ATENCION if difieren else '#666'}; "
        "font-size: 14px; background: transparent;"
    )
    row.addWidget(lbl_arrow)

    lbl_desp = QLabel(str(despues))
    color_desp = _COLOR_ATENCION if difieren else "#999"
    lbl_desp.setStyleSheet(
        f"color: {color_desp}; font-family: 'Consolas', monospace; "
        "font-size: 12px; font-weight: "
        f"{'500' if difieren else 'normal'}; background: transparent;"
    )
    row.addWidget(lbl_desp)

    # Chip informativo
    if difieren:
        row.addWidget(_chip("Modificado", _COLOR_ATENCION))
    else:
        row.addWidget(_chip("Sin cambio", _COLOR_NEUTRAL))

    v.addLayout(row)

    if difieren and justif:
        lbl_just = QLabel(f"Justificación: {justif}")
        lbl_just.setStyleSheet(
            f"color: {_COLOR_ATENCION}; font-size: 11.5px; "
            "background: transparent; padding: 4px 8px 0 8px; font-style: italic;"
        )
        lbl_just.setWordWrap(True)
        v.addWidget(lbl_just)

    parent_lay.addWidget(contenedor)
