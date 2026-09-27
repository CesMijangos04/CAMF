# reportes_render.py
"""
Motor de generación de reportes en PDF (reportlab).

Arquitectura:
    1. Helpers para cargar plantilla y firmas desde BD.
    2. Closure que dibuja encabezado + pie en cada página (logo, empresa,
       paginación, folio, fecha de emisión).
    3. Constructores de 'story' (lista de flowables Platypus) — uno por
       cada tipo_reporte.
    4. Función pública `emitir_reporte(...)` que orquesta:
         - emite folio
         - carga plantilla
         - obtiene datos vía reportes_data
         - construye la story
         - genera el PDF
         - registra el evento en la tabla `reportes`
         - devuelve la ruta del archivo

Para agregar un reporte nuevo:
    1. Crear función en reportes_data.py que devuelva el dict.
    2. Crear función _construir_<tipo>(datos, plantilla) → list aquí.
    3. Añadir el `if tipo_reporte == '<tipo>'` en emitir_reporte.
"""

import os
import json
from datetime import datetime
from typing import Optional, Dict, Any, List, Callable

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, letter, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph,
    Spacer, Table, TableStyle, KeepTogether, PageBreak, Image,
)
from reportlab.pdfgen.canvas import Canvas

from db_manager import connect_db
from reportes_folios import emitir_folio, previsualizar_proximo_folio
from reportes_data import (
    historial_mantenimiento_por_equipo,
    historial_mantenimiento_por_equipos,
)


# ══════════════════════════════════════════════════════════════════════════
#  CONSTANTES DE LAYOUT
# ══════════════════════════════════════════════════════════════════════════

MARGEN_LATERAL   = 18 * mm
ALTURA_ENCABEZADO = 38 * mm   # franja superior reservada para el header
ALTURA_PIE        = 22 * mm   # franja inferior reservada para el footer


# ══════════════════════════════════════════════════════════════════════════
#  HELPERS DE BD (lectura de plantilla y firmas)
# ══════════════════════════════════════════════════════════════════════════

def _obtener_plantilla(plantilla_id: Optional[int] = None) -> Dict[str, Any]:
    """Carga la plantilla por ID o la marcada como predeterminada."""
    conn = connect_db()
    if conn is None:
        return {}
    try:
        cur = conn.cursor()
        if plantilla_id:
            cur.execute("SELECT * FROM reportes_plantillas WHERE id = ?", (plantilla_id,))
        else:
            cur.execute(
                "SELECT * FROM reportes_plantillas WHERE es_predeterminada = 1 LIMIT 1"
            )
        row = cur.fetchone()
        if not row:
            return {}
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))
    finally:
        conn.close()


def _obtener_firmas_predeterminadas() -> List[Dict[str, Any]]:
    """Devuelve las firmas marcadas como predeterminadas para incluir al final."""
    conn = connect_db()
    if conn is None:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT rol, persona_nombre, persona_puesto, persona_cedula,
                   firma_imagen_path
            FROM reportes_firmas
            WHERE es_predeterminada = 1
            ORDER BY rol
        """)
        return [
            {
                'rol':                r[0],
                'nombre':             r[1],
                'puesto':             r[2],
                'cedula':             r[3],
                'firma_imagen_path':  r[4],
            }
            for r in cur.fetchall()
        ]
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════
#  CONFIGURACIÓN DE PÁGINA
# ══════════════════════════════════════════════════════════════════════════

def _tamano_pagina(plantilla: Dict[str, Any]):
    """Devuelve la tupla (ancho, alto) según orientacion + tamano_pagina."""
    base = letter if (plantilla.get('tamano_pagina') or '').lower() == 'carta' else A4
    if (plantilla.get('orientacion') or '').lower() == 'horizontal':
        return landscape(base)
    return base


def _color(hex_str: Optional[str], fallback: str) -> colors.Color:
    """Convierte '#rrggbb' a colors.Color, con fallback seguro."""
    try:
        return colors.HexColor(hex_str or fallback)
    except Exception:
        return colors.HexColor(fallback)


# ══════════════════════════════════════════════════════════════════════════
#  ENCABEZADO Y PIE (closure que recibe canvas + doc en cada página)
# ══════════════════════════════════════════════════════════════════════════

def _crear_dibujador_pagina(
    plantilla: Dict[str, Any],
    folio: str,
    titulo_reporte: str,
) -> Callable:
    """
    Devuelve la función que reportlab llamará en cada página para pintar
    encabezado y pie. La closure captura los datos de plantilla.
    """
    color_principal  = _color(plantilla.get('color_principal'),  '#0078d7')
    color_secundario = _color(plantilla.get('color_secundario'), '#666666')
    fecha_emision    = datetime.now().strftime('%d/%m/%Y %H:%M')

    def dibujar(canvas: Canvas, doc):
        ancho, alto = doc.pagesize
        canvas.saveState()

        # ── ENCABEZADO ────────────────────────────────────────────────
        # Logo o placeholder
        logo_path = plantilla.get('logo_path')
        logo_x = MARGEN_LATERAL
        logo_w = 26 * mm
        logo_h = 20 * mm
        logo_y = alto - 30 * mm

        logo_dibujado = False
        if logo_path and os.path.exists(logo_path):
            try:
                canvas.drawImage(
                    logo_path, logo_x, logo_y,
                    width=logo_w, height=logo_h,
                    preserveAspectRatio=True, mask='auto',
                )
                logo_dibujado = True
            except Exception:
                logo_dibujado = False

        if not logo_dibujado:
            # Placeholder: rectángulo gris con la inicial de la empresa
            canvas.setFillColor(colors.HexColor('#eeeeee'))
            canvas.setStrokeColor(colors.HexColor('#cccccc'))
            canvas.setLineWidth(0.5)
            canvas.rect(logo_x, logo_y, logo_w, logo_h, fill=1, stroke=1)
            canvas.setFillColor(color_principal)
            canvas.setFont('Helvetica-Bold', 16)
            empresa_nombre = plantilla.get('empresa_nombre') or 'CAMF'
            inicial = empresa_nombre[:1].upper() if empresa_nombre else 'C'
            canvas.drawCentredString(
                logo_x + logo_w / 2,
                logo_y + logo_h / 2 - 5,
                inicial,
            )

        # Datos de empresa (alineados a la derecha)
        canvas.setFillColor(color_principal)
        canvas.setFont('Helvetica-Bold', 13)
        empresa = plantilla.get('empresa_nombre') or ''
        canvas.drawRightString(ancho - MARGEN_LATERAL, alto - 14*mm, empresa)

        canvas.setFillColor(color_secundario)
        canvas.setFont('Helvetica', 8.5)
        y_actual = alto - 19 * mm
        lineas_empresa: List[str] = []
        if plantilla.get('empresa_subtitulo'):
            lineas_empresa.append(plantilla['empresa_subtitulo'])
        if plantilla.get('empresa_direccion'):
            lineas_empresa.append(plantilla['empresa_direccion'])
        contacto = []
        if plantilla.get('empresa_telefono'):
            contacto.append(f"Tel. {plantilla['empresa_telefono']}")
        if plantilla.get('empresa_correo'):
            contacto.append(plantilla['empresa_correo'])
        if contacto:
            lineas_empresa.append("  ·  ".join(contacto))
        if plantilla.get('empresa_rfc'):
            lineas_empresa.append(f"RFC: {plantilla['empresa_rfc']}")
        for linea in lineas_empresa:
            canvas.drawRightString(ancho - MARGEN_LATERAL, y_actual, linea)
            y_actual -= 3.8 * mm

        # Línea horizontal bajo el encabezado
        canvas.setStrokeColor(color_principal)
        canvas.setLineWidth(0.8)
        canvas.line(
            MARGEN_LATERAL, alto - 34 * mm,
            ancho - MARGEN_LATERAL, alto - 34 * mm,
        )

        # ── PIE ───────────────────────────────────────────────────────
        canvas.setStrokeColor(colors.HexColor('#cccccc'))
        canvas.setLineWidth(0.4)
        canvas.line(
            MARGEN_LATERAL, 18 * mm,
            ancho - MARGEN_LATERAL, 18 * mm,
        )

        canvas.setFillColor(color_secundario)
        canvas.setFont('Helvetica', 8)

        # Línea 1: Folio (izq) · Emitido (centro) · Página (der)
        if folio:
            canvas.drawString(MARGEN_LATERAL, 13 * mm, f"Folio: {folio}")
        canvas.drawCentredString(ancho / 2, 13 * mm, f"Emitido: {fecha_emision}")
        if plantilla.get('mostrar_paginacion'):
            canvas.drawRightString(
                ancho - MARGEN_LATERAL, 13 * mm,
                f"Página {doc.page}",
            )

        # Línea 2 (opcional): pie_texto centrado
        if plantilla.get('pie_texto'):
            canvas.setFillColor(colors.HexColor('#999999'))
            canvas.setFont('Helvetica-Oblique', 7.5)
            canvas.drawCentredString(ancho / 2, 8 * mm, plantilla['pie_texto'])

        canvas.restoreState()

    return dibujar


# ══════════════════════════════════════════════════════════════════════════
#  ESTILOS REUTILIZABLES PARA EL CUERPO
# ══════════════════════════════════════════════════════════════════════════

def _crear_estilos(plantilla: Dict[str, Any]) -> Dict[str, ParagraphStyle]:
    """Genera un set de ParagraphStyles tematizados con la plantilla."""
    base_size  = int(plantilla.get('tamano_letra') or 10)
    principal  = _color(plantilla.get('color_principal'),  '#0078d7')
    secundario = _color(plantilla.get('color_secundario'), '#666666')

    return {
        'titulo': ParagraphStyle(
            'Titulo', fontName='Helvetica-Bold',
            fontSize=18, leading=22, alignment=TA_LEFT,
            textColor=principal,
            spaceBefore=0, spaceAfter=2,
        ),
        'subtitulo': ParagraphStyle(
            'Subtitulo', fontName='Helvetica',
            fontSize=11, leading=14, alignment=TA_LEFT,
            textColor=colors.HexColor('#444444'),
            spaceBefore=0, spaceAfter=12,
        ),
        'seccion': ParagraphStyle(
            'Seccion', fontName='Helvetica-Bold',
            fontSize=10, leading=12, alignment=TA_LEFT,
            textColor=principal,
            spaceBefore=14, spaceAfter=6,
        ),
        'body': ParagraphStyle(
            'Body', fontName='Helvetica',
            fontSize=base_size, leading=base_size + 3,
            textColor=colors.HexColor('#222222'),
        ),
        'body_chico': ParagraphStyle(
            'BodyChico', fontName='Helvetica',
            fontSize=base_size - 1, leading=base_size + 1,
            textColor=colors.HexColor('#222222'),
        ),
        'etiqueta': ParagraphStyle(
            'Etiqueta', fontName='Helvetica-Bold',
            fontSize=base_size, leading=base_size + 2,
            textColor=secundario,
        ),
        'urgente_chip': ParagraphStyle(
            'UrgenteChip', fontName='Helvetica-Bold',
            fontSize=base_size - 2, leading=base_size,
            textColor=colors.white,
            backColor=colors.HexColor('#c0392b'),
        ),
    }


# ══════════════════════════════════════════════════════════════════════════
#  CONSTRUCTORES DE STORY POR TIPO DE REPORTE
# ══════════════════════════════════════════════════════════════════════════

def _construir_historial_mantenimiento(
    datos: Dict[str, Any],
    plantilla: Dict[str, Any],
) -> List:
    """
    Construye la story Platypus para 'historial_equipo'.

    Soporta dos casos:
      - 1 equipo:  layout clásico — datos equipo + resumen + tabla eventos.
      - N equipos: resumen global arriba + una sección por equipo
                   (cada equipo arranca en página propia).
    """
    estilos = _crear_estilos(plantilla)
    principal  = _color(plantilla.get('color_principal'),  '#0078d7')
    secundario = _color(plantilla.get('color_secundario'), '#666666')
    base_size  = int(plantilla.get('tamano_letra') or 10)

    secciones = datos.get('secciones', [])
    n_equipos = len(secciones)
    es_multi  = n_equipos > 1

    story: List = []

    # ── Título y subtítulo ─────────────────────────────────────────────
    story.append(Paragraph(datos.get('titulo', 'Reporte'), estilos['titulo']))
    if datos.get('subtitulo'):
        story.append(Paragraph(datos['subtitulo'], estilos['subtitulo']))

    # ── Período (solo si está acotado) ─────────────────────────────────
    rango = datos.get('rango_fechas') or {}
    if rango.get('desde') or rango.get('hasta'):
        desde = rango.get('desde') or 'el inicio del registro'
        hasta = rango.get('hasta') or 'hoy'
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            f"<b>Período cubierto:</b> {desde} a {hasta}",
            estilos['body']
        ))

    # ── Caso multi-equipo: resumen global arriba ───────────────────────
    if es_multi:
        rg = datos.get('resumen_global') or {}
        story.append(Paragraph(
            f"RESUMEN GLOBAL · {n_equipos} EQUIPOS",
            estilos['seccion'],
        ))
        story.extend(_tabla_resumen(rg, estilos, secundario, base_size))

    # ── Sin secciones (ningún equipo encontrado en BD) ─────────────────
    if n_equipos == 0:
        story.append(Spacer(1, 12))
        story.append(Paragraph(
            "No se encontraron datos para los equipos seleccionados.",
            estilos['body'],
        ))
    else:
        # ── Por cada equipo: bloque completo ───────────────────────────
        for idx, seccion in enumerate(secciones):
            # Salto de página entre equipos en modo multi.
            # El primero NO tiene salto: queda inmediatamente después del
            # resumen global. Si quisieras que cada equipo tenga su página
            # propia desde el inicio, cambia esto a `if es_multi:`.
            if es_multi and idx > 0:
                story.append(PageBreak())

            story.extend(_bloque_seccion_equipo(
                seccion, estilos, principal, secundario, base_size,
                con_subheader=es_multi,
                indice=idx + 1,
                total=n_equipos,
            ))

    # ── Firmas (al final, en página propia si la story es larga) ───────
    firmas = _obtener_firmas_predeterminadas()
    if firmas:
        bloque_firmas: List = [
            Spacer(1, 24),
            Paragraph("FIRMAS", estilos['seccion']),
            Spacer(1, 36),
        ]
        cols = min(len(firmas), 3)
        rows_firmas: List = []
        fila_actual: List = []
        for f in firmas:
            nombre = f.get('nombre') or ''
            puesto = f.get('puesto') or ''
            cedula = f.get('cedula') or ''
            rol    = f.get('rol') or ''
            img_path = f.get('firma_imagen_path')

            # Texto que va debajo de la línea
            partes_texto = [f"<b>{nombre}</b>"]
            if puesto:
                partes_texto.append(puesto)
            elif rol:
                partes_texto.append(rol.replace('_', ' ').title())
            if cedula:
                partes_texto.append(f"<font color='#888888'>Céd. Prof. {cedula}</font>")
            texto_debajo = Paragraph(
                '<br/>'.join(partes_texto), estilos['body_chico']
            )

            # Si hay imagen de firma, armamos una mini-tabla:
            #   [ imagen escaneada ]
            #   [ línea horizontal ]
            #   [ nombre + puesto + cédula ]
            celda = None
            if img_path and os.path.exists(img_path):
                try:
                    img = Image(img_path, width=42*mm, height=14*mm,
                                kind='proportional')
                    linea = Paragraph(
                        "<font color='#999999'>____________________________</font>",
                        estilos['body_chico'],
                    )
                    mini = Table(
                        [[img], [linea], [texto_debajo]],
                        colWidths=[None],
                    )
                    mini.setStyle(TableStyle([
                        ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
                        ('LEFTPADDING',   (0, 0), (-1, -1), 0),
                        ('RIGHTPADDING',  (0, 0), (-1, -1), 0),
                        ('TOPPADDING',    (0, 0), (-1, -1), 1),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
                    ]))
                    celda = mini
                except Exception:
                    celda = None

            if celda is None:
                # Sin imagen: línea + texto en un solo Paragraph (estilo clásico)
                partes_html = ["____________________________"] + partes_texto
                celda = Paragraph('<br/>'.join(partes_html), estilos['body_chico'])

            fila_actual.append(celda)
            if len(fila_actual) == cols:
                rows_firmas.append(fila_actual)
                fila_actual = []
        if fila_actual:
            while len(fila_actual) < cols:
                fila_actual.append('')
            rows_firmas.append(fila_actual)

        if rows_firmas:
            t_firmas = Table(rows_firmas, colWidths=[None] * cols)
            t_firmas.setStyle(TableStyle([
                ('VALIGN',        (0, 0), (-1, -1), 'BOTTOM'),
                ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
                ('TOPPADDING',    (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ]))
            bloque_firmas.append(t_firmas)

        story.append(KeepTogether(bloque_firmas))

    return story


# ──────────────────────────────────────────────────────────────────────────
#  Helpers internos del constructor de historial
# ──────────────────────────────────────────────────────────────────────────

def _tabla_resumen(
    resumen: Dict[str, Any],
    estilos: Dict[str, Any],
    color_secundario,
    base_size: int,
) -> List:
    """Devuelve la tabla compacta de resumen (total eventos, costos, etc.)."""
    if not resumen or resumen.get('total_eventos', 0) == 0:
        return [Paragraph(
            "No hay eventos registrados en el período seleccionado.",
            estilos['body'],
        )]
    moneda = resumen.get('costo_moneda', 'MXN')
    costo_total = resumen.get('costo_total', 0.0)
    rows = [
        ['Total de eventos', str(resumen.get('total_eventos', 0))],
        ['Finalizados',      str(resumen.get('finalizados', 0))],
        ['Cancelados',       str(resumen.get('cancelados', 0))],
        ['Preventivos',      str(resumen.get('preventivos', 0))],
        ['Correctivos',      str(resumen.get('correctivos', 0))],
        ['Costo total',      f"${costo_total:,.2f} {moneda}"],
    ]
    tbl = Table(rows, colWidths=[60 * mm, 50 * mm])
    tbl.setStyle(TableStyle([
        ('FONTSIZE',     (0, 0), (-1, -1), base_size),
        ('FONTNAME',     (0, 0), (0, -1), 'Helvetica'),
        ('FONTNAME',     (1, 0), (1, -1), 'Helvetica-Bold'),
        ('TEXTCOLOR',    (0, 0), (0, -1), color_secundario),
        ('TEXTCOLOR',    (1, 0), (1, -1), colors.HexColor('#222222')),
        ('LEFTPADDING',  (0, 0), (-1, -1), 0),
        ('TOPPADDING',   (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 2),
        ('LINEABOVE',    (0, -1), (-1, -1), 0.4, colors.HexColor('#cccccc')),
        ('TOPPADDING',   (0, -1), (-1, -1), 6),
    ]))
    return [tbl]


def _bloque_seccion_equipo(
    seccion: Dict[str, Any],
    estilos: Dict[str, Any],
    color_principal,
    color_secundario,
    base_size: int,
    con_subheader: bool,
    indice: int,
    total: int,
) -> List:
    """
    Story de UN equipo: encabezado del equipo + datos + resumen + tabla
    de eventos.
    """
    equipo = seccion.get('equipo', {})
    mantenimientos = seccion.get('mantenimientos', [])
    resumen = seccion.get('resumen', {})

    bloque: List = []

    # Subheader del equipo (solo en modo multi).
    # Ej: "EQUIPO 2 DE 5 · Tablero TG-02"
    if con_subheader:
        subheader = (
            f"EQUIPO {indice} DE {total} · "
            f"{equipo.get('tipo_equipo', '')} {equipo.get('identificador', '')}"
        ).strip()
        bloque.append(Paragraph(subheader, estilos['seccion']))
    else:
        bloque.append(Paragraph("DATOS DEL EQUIPO", estilos['seccion']))

    # Datos del equipo
    info_rows: List = []
    if equipo.get('ubicacion'):
        info_rows.append([
            Paragraph("Ubicación:", estilos['etiqueta']),
            Paragraph(str(equipo['ubicacion']), estilos['body']),
        ])
    for etiqueta, valor in equipo.get('datos_tecnicos', []):
        info_rows.append([
            Paragraph(f"{etiqueta}:", estilos['etiqueta']),
            Paragraph(str(valor), estilos['body']),
        ])
    if info_rows:
        tbl = Table(info_rows, colWidths=[45 * mm, None])
        tbl.setStyle(TableStyle([
            ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING',   (0, 0), (-1, -1), 0),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 6),
            ('TOPPADDING',    (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        bloque.append(tbl)

    # Resumen del equipo (solo si hay eventos)
    if resumen.get('total_eventos', 0) > 0:
        bloque.append(Paragraph("RESUMEN", estilos['seccion']))
        bloque.extend(_tabla_resumen(resumen, estilos, color_secundario, base_size))

    # Tabla de eventos
    bloque.append(Paragraph(
        f"EVENTOS REGISTRADOS ({len(mantenimientos)})",
        estilos['seccion'],
    ))
    if not mantenimientos:
        bloque.append(Paragraph(
            "No hay eventos registrados en el período seleccionado.",
            estilos['body'],
        ))
    else:
        estilo_celda = ParagraphStyle(
            'Celda', parent=estilos['body_chico'], alignment=TA_LEFT,
        )
        estilo_celda_num = ParagraphStyle(
            'CeldaNum', parent=estilos['body_chico'], alignment=2,  # TA_RIGHT
        )
        estilo_celda_centro = ParagraphStyle(
            'CeldaCentro', parent=estilos['body_chico'], alignment=1,  # TA_CENTER
        )
        encabezados = ['Fecha', 'Tipo', 'Estado', 'Responsable', 'Costo', 'Descripción']
        col_widths = [20*mm, 28*mm, 22*mm, 32*mm, 20*mm, None]
        rows = [encabezados]
        for m in mantenimientos:
            fecha = (m.get('fecha_inicio') or '—')[:10]
            tipo  = m.get('tipo') or '—'
            estado = (m.get('estado') or '—').title()
            responsable = m.get('responsable') or '—'
            costo_val = m.get('costo_real') if m.get('costo_real') else m.get('costo')
            costo = f"${costo_val:,.0f}" if costo_val else "—"
            desc = m.get('descripcion') or m.get('retroalimentacion') or '—'
            rows.append([
                Paragraph(fecha,       estilo_celda_centro),
                Paragraph(tipo,        estilo_celda),
                Paragraph(estado,      estilo_celda_centro),
                Paragraph(responsable, estilo_celda),
                Paragraph(costo,       estilo_celda_num),
                Paragraph(desc,        estilo_celda),
            ])
        tbl = Table(rows, colWidths=col_widths, repeatRows=1)
        tbl.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), color_principal),
            ('TEXTCOLOR',  (0, 0), (-1, 0), colors.white),
            ('FONTNAME',   (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE',   (0, 0), (-1, 0), base_size),
            ('ALIGN',      (0, 0), (-1, 0), 'LEFT'),
            ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID',           (0, 0), (-1, -1), 0.3, colors.HexColor('#cccccc')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f7f7f7')]),
            ('LEFTPADDING',   (0, 0), (-1, -1), 5),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 5),
            ('TOPPADDING',    (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        bloque.append(tbl)

    return bloque


# ══════════════════════════════════════════════════════════════════════════
#  DISPATCHER + EMISIÓN EN DOS FASES (preview + confirmación)
# ══════════════════════════════════════════════════════════════════════════

# Mapeo tipo_reporte → (función de datos, función constructora de story)
_REGISTRO_REPORTES: Dict[str, Dict[str, Callable]] = {
    'historial_equipo': {
        # Soporta tanto 1 como N equipos. Los parámetros esperados son:
        #   {'equipos': [{'id', 'tipo'}, ...], 'fecha_inicio': ..., 'fecha_fin': ...}
        'datos':     historial_mantenimiento_por_equipos,
        'construir': _construir_historial_mantenimiento,
    },
    # Cuando agregues más reportes:
    # 'programa_anual':  {'datos': ..., 'construir': ...},
    # 'cuadro_cargas':   {'datos': ..., 'construir': ...},
    # ...
}


# ──────────────────────────────────────────────────────────────────────────
#  Información del preview, reusable al confirmar
# ──────────────────────────────────────────────────────────────────────────

from dataclasses import dataclass, field

@dataclass
class PreviewReporte:
    """
    Resultado de construir_pdf_preview(). Contiene todo lo necesario para
    consultar el PDF temporal y, si el usuario decide, confirmarlo como
    oficial sin re-consultar BD.
    """
    ruta_temp: str                # path absoluto del PDF temporal
    folio_preview: str            # folio que se asignaría (no consumido)
    plantilla: Dict[str, Any]     # plantilla usada (snapshot)
    datos: Dict[str, Any]         # datos resueltos del reporte
    categoria: str
    tipo_reporte: str
    parametros: Dict[str, Any]

    # Si el usuario ya confirmó este preview, guardamos la ruta oficial
    # para no permitir confirmarlo dos veces.
    confirmado: bool = field(default=False)
    ruta_oficial: Optional[str] = field(default=None)


# ──────────────────────────────────────────────────────────────────────────
#  Helper: renderiza el PDF a una ruta dada con un folio dado
# ──────────────────────────────────────────────────────────────────────────

def _render_pdf(
    ruta_destino: str,
    plantilla: Dict[str, Any],
    datos: Dict[str, Any],
    tipo_reporte: str,
    folio: str,
    categoria: str,
) -> None:
    """
    Renderea el PDF en `ruta_destino` con el folio dado. No toca BD.
    Esta función es el corazón del motor: la usan tanto el preview
    (con folio peekeado) como la confirmación (con folio real).
    """
    pagesize = _tamano_pagina(plantilla)

    doc = BaseDocTemplate(
        ruta_destino,
        pagesize=pagesize,
        leftMargin=MARGEN_LATERAL,
        rightMargin=MARGEN_LATERAL,
        topMargin=ALTURA_ENCABEZADO + 4 * mm,
        bottomMargin=ALTURA_PIE,
        title=datos.get('titulo', 'Reporte CAMF'),
        author=plantilla.get('empresa_nombre') or 'CAMF',
        subject=f"Categoría: {categoria} · Tipo: {tipo_reporte}",
    )
    frame = Frame(
        x1=MARGEN_LATERAL,
        y1=ALTURA_PIE,
        width=pagesize[0] - 2 * MARGEN_LATERAL,
        height=pagesize[1] - ALTURA_ENCABEZADO - ALTURA_PIE - 4 * mm,
        leftPadding=0, rightPadding=0,
        topPadding=0, bottomPadding=0,
        id='cuerpo',
    )
    dibujador = _crear_dibujador_pagina(plantilla, folio, datos.get('titulo', ''))
    template = PageTemplate(id='principal', frames=[frame], onPage=dibujador)
    doc.addPageTemplates([template])

    fn_construir = _REGISTRO_REPORTES[tipo_reporte]['construir']
    story = fn_construir(datos, plantilla)
    doc.build(story)


# ──────────────────────────────────────────────────────────────────────────
#  FASE 1 — Preview (no consume folio, no toca BD)
# ──────────────────────────────────────────────────────────────────────────

def construir_pdf_preview(
    categoria: str,
    tipo_reporte: str,
    parametros: Dict[str, Any],
    plantilla_id: Optional[int] = None,
) -> PreviewReporte:
    """
    Construye un PDF temporal para que el usuario lo consulte ANTES de
    decidir si se emite oficialmente.

    NO consume folio (solo lo "peekea") y NO registra nada en BD.
    El archivo queda en %TEMP%/camf_preview_<...>.pdf y debe limpiarse
    con eliminar_temp() cuando el preview se cierre.

    Para confirmar el preview, llamar confirmar_pdf_oficial(preview).
    """
    if tipo_reporte not in _REGISTRO_REPORTES:
        raise ValueError(f"Tipo de reporte no implementado: '{tipo_reporte}'")

    plantilla = _obtener_plantilla(plantilla_id)
    if not plantilla:
        raise RuntimeError(
            "No hay plantilla configurada. "
            "Ve a Configuración → Reportes → Plantillas para configurar una."
        )

    # 1) Resolver datos (lectura de BD, no escribe nada)
    fn_datos = _REGISTRO_REPORTES[tipo_reporte]['datos']
    datos = fn_datos(**parametros)

    # 2) Peek del folio que TOCARÍA emitir (no lo consume)
    folio_preview = previsualizar_proximo_folio(categoria) or "—"

    # 3) Crear archivo temporal y renderear
    import tempfile
    fd, ruta_temp = tempfile.mkstemp(
        suffix='.pdf', prefix='camf_preview_'
    )
    os.close(fd)

    _render_pdf(
        ruta_destino=ruta_temp,
        plantilla=plantilla,
        datos=datos,
        tipo_reporte=tipo_reporte,
        folio=folio_preview,
        categoria=categoria,
    )

    return PreviewReporte(
        ruta_temp=ruta_temp,
        folio_preview=folio_preview,
        plantilla=plantilla,
        datos=datos,
        categoria=categoria,
        tipo_reporte=tipo_reporte,
        parametros=parametros,
    )


# ──────────────────────────────────────────────────────────────────────────
#  FASE 2 — Confirmación oficial (consume folio + registra en BD)
# ──────────────────────────────────────────────────────────────────────────

def confirmar_pdf_oficial(
    preview: PreviewReporte,
    ruta_destino: Optional[str] = None,
) -> str:
    """
    Convierte un preview en un reporte oficial:
      - consume el folio (atómico)
      - re-renderea con el folio definitivo (si cambió por concurrencia)
      - guarda en la carpeta oficial (%LOCALAPPDATA%/CAMF/reportes/)
      - registra en la tabla `reportes`
      - marca el preview como confirmado para que no pueda reusarse

    Devuelve la ruta del archivo oficial.
    """
    if preview.confirmado:
        # Idempotencia: si por error se llama dos veces, devolvemos el path
        # que ya existe en lugar de quemar otro folio.
        return preview.ruta_oficial or preview.ruta_temp

    # 1) Emitir folio (atómico — esta es la única vez que se consume)
    folio_real = emitir_folio(preview.categoria)

    # 2) Resolver ruta de destino oficial
    if ruta_destino is None:
        base_dir = os.path.join(
            os.getenv('LOCALAPPDATA') or os.path.expanduser('~'),
            'CAMF', 'reportes',
        )
        os.makedirs(base_dir, exist_ok=True)
        safe_folio = folio_real.replace('/', '-').replace('\\', '-')
        ruta_destino = os.path.join(base_dir, f"{safe_folio}.pdf")
    else:
        os.makedirs(os.path.dirname(ruta_destino) or '.', exist_ok=True)

    # 3) Renderear con el folio real (reutiliza plantilla y datos del preview)
    _render_pdf(
        ruta_destino=ruta_destino,
        plantilla=preview.plantilla,
        datos=preview.datos,
        tipo_reporte=preview.tipo_reporte,
        folio=folio_real,
        categoria=preview.categoria,
    )

    # 4) Registrar en bitácora
    _registrar_emision(
        categoria=preview.categoria,
        tipo_reporte=preview.tipo_reporte,
        folio=folio_real,
        plantilla_id=preview.plantilla['id'],
        parametros=preview.parametros,
        ruta=ruta_destino,
    )

    preview.confirmado = True
    preview.ruta_oficial = ruta_destino
    return ruta_destino


def eliminar_temp(preview: PreviewReporte) -> None:
    """Borra el PDF temporal del preview. Seguro de llamar varias veces."""
    try:
        if preview.ruta_temp and os.path.exists(preview.ruta_temp):
            os.remove(preview.ruta_temp)
    except Exception:
        # No hacemos ruido si la limpieza falla (Windows a veces tarda
        # en liberar archivos abiertos por pymupdf).
        pass


# ──────────────────────────────────────────────────────────────────────────
#  Conveniencia: emitir directo en una sola llamada (preview + confirm)
# ──────────────────────────────────────────────────────────────────────────

def emitir_reporte(
    categoria: str,
    tipo_reporte: str,
    parametros: Dict[str, Any],
    plantilla_id: Optional[int] = None,
    ruta_destino: Optional[str] = None,
) -> str:
    """
    Convenience: construye preview + lo confirma inmediatamente. Útil
    cuando no se necesita interacción del usuario (tests, batch).

    El preview temporal se limpia al final.
    """
    preview = construir_pdf_preview(
        categoria=categoria,
        tipo_reporte=tipo_reporte,
        parametros=parametros,
        plantilla_id=plantilla_id,
    )
    try:
        return confirmar_pdf_oficial(preview, ruta_destino=ruta_destino)
    finally:
        eliminar_temp(preview)


def _registrar_emision(
    categoria: str,
    tipo_reporte: str,
    folio: str,
    plantilla_id: int,
    parametros: Dict[str, Any],
    ruta: str,
) -> None:
    """Inserta un renglón en la tabla `reportes` con la metadata del PDF emitido."""
    conn = connect_db()
    if conn is None:
        return
    try:
        conn.execute("""
            INSERT INTO reportes
                (categoria, tipo_reporte, folio, fecha,
                 formato, plantilla_id, parametros_json, archivo_ruta)
            VALUES (?, ?, ?, ?, 'pdf', ?, ?, ?)
        """, (
            categoria,
            tipo_reporte,
            folio,
            datetime.now().isoformat(timespec='seconds'),
            plantilla_id,
            json.dumps(parametros, ensure_ascii=False),
            ruta,
        ))
        conn.commit()
    finally:
        conn.close()
