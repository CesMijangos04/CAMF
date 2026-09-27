from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors


def generar_pdf_tablero(archivo, tablero_data, circuitos, num_circuitos):

    circuitos_pos = [None] * num_circuitos
    for c in (circuitos or []):
        if not c:
            continue
        inicio = c.get("espacio_inicio")
        polos = c.get("polos", 1)
        if inicio is None:
            continue
        idx0 = inicio - 1  # base 0
        if idx0 < 0 or idx0 >= num_circuitos:
            continue
        # Espacio inicial: dict completo (con alias 'fases' para compat. interna)
        dato_inicial = dict(c)
        dato_inicial["fases"] = polos
        circuitos_pos[idx0] = dato_inicial
        # Continuaciones (bi/trifásico): nombre=None pero comparten 'inicio'
        for k in range(1, polos):
            pos = idx0 + k * 2
            if pos < num_circuitos:
                circuitos_pos[pos] = {
                    "nombre": None,
                    "inicio": idx0,
                    "polos": polos,
                    "fases": polos,
                }
    circuitos = circuitos_pos

    c = canvas.Canvas(archivo, pagesize=A4)
    ancho, alto = A4

    margen_x = 20 * mm
    margen_y = 20 * mm
    alto_encabezado = 40 * mm  # un poco más alto para 3 líneas

    # =====================
    # ENCABEZADO (3 LÍNEAS)
    # =====================
    y = alto - margen_y

    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(
        ancho / 2,
        y,
        f"{tablero_data['id']} – {tablero_data['ubicacion']}"
    )

    c.setFont("Helvetica", 10)
    c.drawCentredString(
        ancho / 2,
        y - 14,
        f"V: {tablero_data['tension']} V     "
        f"I: {tablero_data['corriente']} A     "
        f"Tipo: {tablero_data['tipo']}"
    )

    c.drawCentredString(
        ancho / 2,
        y - 28,
        f"Marca: {tablero_data['marca']}"
    )

    # =====================
    # CONSTRUIR TABLA
    # =====================
    tabla_data = [
        ["C", "Descripción", "C", "Descripción"]
    ]

    # Spans verticales en columnas de descripción para circuitos bi/trifásicos.
    # Formato de SPAN: ('SPAN', (col_inicio, fila_inicio), (col_fin, fila_fin))
    spans = []

    def _nombre_visible(circuitos_list, idx, num_circuitos):
        """
        Devuelve el nombre real del circuito en la posición idx.
        Para bi/trifásicos, los espacios siguientes tienen nombre=None
        pero comparten el mismo 'inicio'. Solo el primer espacio del bloque
        muestra texto en el PDF (los siguientes quedan vacíos y se fusionan).
        Devuelve None si la celda debe quedar vacía (porque será absorbida por un span).
        """
        if idx >= num_circuitos or idx >= len(circuitos_list):
            return ""
        c = circuitos_list[idx]
        if not c:
            return ""
        # Solo el espacio inicial del bloque escribe su nombre
        return c.get("nombre") or ""

    def _span_largo(circuitos_list, idx, num_circuitos):
        """
        Cuántas filas hacia abajo abarca este circuito (1 mono, 2 bi, 3 tri).
        Solo cuenta si idx es el inicio del bloque (tiene 'nombre' real).
        Devuelve 1 si es monofásico o si no debe generar span.
        """
        if idx >= num_circuitos or idx >= len(circuitos_list):
            return 1
        c = circuitos_list[idx]
        if not c or not c.get("nombre"):
            return 1
        return int(c.get("fases", 1))

    fila_tabla = 1  # fila 0 es el encabezado
    i = 0
    while i < num_circuitos:
        j = i + 1  # posición de la derecha

        # ── Lado izquierdo ─────────────────────────────────────────
        num_izq = str(i + 1)
        nombre_izq = _nombre_visible(circuitos, i, num_circuitos)

        # ── Lado derecho ───────────────────────────────────────────
        num_der = str(j + 1) if j < num_circuitos else ""
        nombre_der = _nombre_visible(circuitos, j, num_circuitos)

        tabla_data.append([num_izq, nombre_izq, num_der, nombre_der])

        # Registrar SPAN si es bi/trifásico (descripción ocupa varias filas)
        # Las columnas C (0 y 2) se quedan como filas separadas (1,3,5…)
        # Las columnas de descripción (1 y 3) se fusionan.
        largo_izq = _span_largo(circuitos, i, num_circuitos)
        if largo_izq > 1:
            spans.append(('SPAN', (1, fila_tabla), (1, fila_tabla + largo_izq - 1)))

        largo_der = _span_largo(circuitos, j, num_circuitos)
        if largo_der > 1:
            spans.append(('SPAN', (3, fila_tabla), (3, fila_tabla + largo_der - 1)))

        i += 2
        fila_tabla += 1

    # =====================
    # TABLA
    # =====================
    inicio_tabla_y = alto - margen_y - alto_encabezado

    ancho_c = 12 * mm
    ancho_desc = 55 * mm
    ancho_total_tabla = (ancho_c + ancho_desc) * 2

    table = Table(
        tabla_data,
        colWidths=[ancho_c, ancho_desc, ancho_c, ancho_desc]
    )

    table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ] + spans))

    # wrapOn calcula el tamaño real que ocupará la tabla (incluye paddings internos)
    ancho_real, alto_real = table.wrapOn(c, ancho, alto)
    # Centrar horizontalmente usando el ancho real calculado por ReportLab
    x_centro = (ancho - ancho_real) / 2
    table.drawOn(c, x_centro, inicio_tabla_y - alto_real)


    c.showPage()
    c.save()
