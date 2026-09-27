"""
datos_proyecto.py
=================

Modelo en memoria de un proyecto abierto en su espacio de trabajo.

Sesión C + D del módulo Proyectos.

Contiene:
  * PlanoDeProyecto — dataclass mutable con la info de un plano
    cargado: título, path del archivo, escala calibrada opcional,
    fecha de carga, thumbnail cacheado, y (Sesión D) listas de muros
    y habitaciones dibujados sobre el plano.
  * Muro (Sesión D) — polilínea de vértices en pt PDF.
  * Habitacion (Sesión D) — polígono cerrado con nombre y área
    calculada por la escala.
  * ProyectoAbierto — QObject que envuelve la metadata del proyecto
    (viene del wizard como dict) y gestiona planos + muros +
    habitaciones, exponiendo signals que la UI escucha para reaccionar
    a cambios sin acoplamiento fuerte.

Persistencia:
  Todo vive en RAM. Cuando se conecte SQLite en una fase posterior,
  los métodos de agregar/eliminar/actualizar delegarán a db_manager
  sin que la UI se entere.

Convenciones del módulo Proyectos:
  * Self-contained: paleta local, sin imports cruzados de otros
    módulos de CAMF salvo escala_calibrador (que ya vive junto en
    proyectos/).
  * Signals estilo Qt para comunicar cambios al UI.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap

from escala_calibrador import EscalaCalibrada


# ---------------------------------------------------------------------------
# Enums de Delimitación (Sesión D)
# ---------------------------------------------------------------------------

class TipoMaterialMuro(Enum):
    """Material físico del muro. Determina cómo el motor de agrupación
    trata las trayectorias que lo cruzan y qué canalizaciones son
    válidas según NOM-001-SEDE.

    * CONCRETO_ARMADO — muro estructural con acero. Perforación cara.
    * BLOCK — block de concreto. Perforación media.
    * TABIQUE_LADRILLO — mampostería tradicional. Perforación fácil.
    * TABLAROCA — muro seco (yeso sobre bastidor metálico). Ideal
      para canalización oculta a través. Perforación trivial.
    * DIVISORIO_LIGERO — cancelería, vidrio, madera fina. No apto
      para canalización oculta.
    * MIXTO — muro compuesto (concreto abajo + tabique arriba, etc.).
    * SIN_ESPECIFICAR — para muros dibujados sin decidir material aún.
    """
    CONCRETO_ARMADO   = "concreto_armado"
    BLOCK             = "block"
    TABIQUE_LADRILLO  = "tabique_ladrillo"
    TABLAROCA         = "tablaroca"
    DIVISORIO_LIGERO  = "divisorio_ligero"
    MIXTO             = "mixto"
    SIN_ESPECIFICAR   = "sin_especificar"


# Labels legibles para el UI. Se mantienen aquí para que el material
# tenga una única fuente de verdad (BD, UI, reportes).
MATERIAL_MURO_LABELS: dict[TipoMaterialMuro, str] = {
    TipoMaterialMuro.CONCRETO_ARMADO:   "Concreto armado",
    TipoMaterialMuro.BLOCK:             "Block",
    TipoMaterialMuro.TABIQUE_LADRILLO:  "Tabique / Ladrillo",
    TipoMaterialMuro.TABLAROCA:         "Tablaroca",
    TipoMaterialMuro.DIVISORIO_LIGERO:  "Divisorio ligero",
    TipoMaterialMuro.MIXTO:             "Mixto",
    TipoMaterialMuro.SIN_ESPECIFICAR:   "Sin especificar",
}


# Grosor default (en cm) de cada tipo de material. Se aplica cuando el
# usuario no especifica un grosor explícito para el muro. Valores
# típicos de construcción mexicana residencial / oficinas ligeras.
GROSOR_DEFAULT_POR_MATERIAL: dict[TipoMaterialMuro, float] = {
    TipoMaterialMuro.CONCRETO_ARMADO:   20.0,
    TipoMaterialMuro.BLOCK:             12.0,
    TipoMaterialMuro.TABIQUE_LADRILLO:  14.0,
    TipoMaterialMuro.TABLAROCA:         10.0,
    TipoMaterialMuro.DIVISORIO_LIGERO:   6.0,
    TipoMaterialMuro.MIXTO:             15.0,
    TipoMaterialMuro.SIN_ESPECIFICAR:   12.0,
}


class TipoGeometriaMuro(Enum):
    """Geometría del trazo de un muro.

    * LINEAL — polilínea de N vértices. Cada segmento es una recta.
      El caso general de la herramienta "Muro".
    * ARCO — arco por 3 puntos (inicio, punto por el que pasa el arco,
      fin). Los vértices del muro almacenan exactamente esos 3
      puntos de control; la circunferencia y el arco se calculan al
      renderizar / medir. El motor de canalizaciones tratará este
      muro como una curva continua para trazar canalizaciones
      paralelas al muro.
    """
    LINEAL = "lineal"
    ARCO   = "arco"


class JustificacionMuro(Enum):
    """Hacia qué lado del eje dibujado se aplica el grosor del muro.

    Al dibujar el usuario traza una línea. El grosor físico del muro
    se pinta como polígono alrededor de esa línea. Esta justificación
    dice CÓMO se posiciona:

    * CENTRO — mitad del grosor a cada lado del eje (default). Es lo
      natural cuando el usuario dibuja siguiendo el eje central del
      muro.
    * IZQUIERDA — todo el grosor va hacia la izquierda del sentido de
      recorrido (del vértice inicial al final). Útil cuando el usuario
      está trazando la CARA DERECHA del muro y quiere que todo el
      grosor quede al otro lado.
    * DERECHA — todo el grosor va hacia la derecha del sentido de
      recorrido. Simétrico al anterior.

    "Izquierda" y "derecha" se refieren a mirar hacia adelante en el
    sentido de dibujo — es la convención estándar de CAD arquitectónico.
    """
    CENTRO     = "centro"
    IZQUIERDA  = "izquierda"
    DERECHA    = "derecha"


JUSTIFICACION_MURO_LABELS: dict[JustificacionMuro, str] = {
    JustificacionMuro.CENTRO:    "Centro (eje al medio)",
    JustificacionMuro.IZQUIERDA: "Cara izquierda (grosor a la izquierda)",
    JustificacionMuro.DERECHA:   "Cara derecha (grosor a la derecha)",
}


class TipoUsoHabitacion(Enum):
    """Tipo/uso de una habitación. Lo usa el motor para:
      * Elegir agrupación de circuitos según NOM-001 (baños y cocinas
        → GFCI, dedicados; recámaras → 3 vías; etc.).
      * Estimar densidad de carga con tablas NOM por uso.
      * Aplicar reglas específicas (IP66 en exteriores, etc.).

    Notas:
      * DUCTO_SERVICIO — espacio vertical/horizontal reservado para
        pasar canalizaciones eléctricas, hidráulicas, etc. (ducto
        técnico). No es una habitación habitable, pero se dibuja como
        polígono cerrado para que el motor de agrupación lo trate
        como zona de tránsito preferente de circuitos verticales
        entre pisos.
    """
    SALA           = "sala"
    COMEDOR        = "comedor"
    COCINA         = "cocina"
    BANO           = "bano"
    DORMITORIO     = "dormitorio"
    OFICINA        = "oficina"
    SALON_AULA     = "salon_aula"
    PASILLO        = "pasillo"
    ESCALERA       = "escalera"
    TERRAZA_AZOTEA = "terraza_azotea"
    AREA_COMUN     = "area_comun"
    DUCTO_SERVICIO = "ducto_servicio"
    OTRO           = "otro"


USO_HABITACION_LABELS: dict[TipoUsoHabitacion, str] = {
    TipoUsoHabitacion.SALA:           "Sala",
    TipoUsoHabitacion.COMEDOR:        "Comedor",
    TipoUsoHabitacion.COCINA:         "Cocina",
    TipoUsoHabitacion.BANO:           "Baño",
    TipoUsoHabitacion.DORMITORIO:     "Dormitorio / Recámara",
    TipoUsoHabitacion.OFICINA:        "Oficina",
    TipoUsoHabitacion.SALON_AULA:     "Salón / Aula",
    TipoUsoHabitacion.PASILLO:        "Pasillo",
    TipoUsoHabitacion.ESCALERA:       "Escalera",
    TipoUsoHabitacion.TERRAZA_AZOTEA: "Terraza / Azotea",
    TipoUsoHabitacion.AREA_COMUN:     "Área común",
    TipoUsoHabitacion.DUCTO_SERVICIO: "Ducto de servicio",
    TipoUsoHabitacion.OTRO:           "Otro",
}

try:
    import fitz  # pymupdf
    _PYMUPDF_OK = True
except Exception:  # noqa: BLE001
    _PYMUPDF_OK = False


# ---------------------------------------------------------------------------
# Muro y Habitacion (Sesión D — Delimitación)
# ---------------------------------------------------------------------------

@dataclass
class Muro:
    """Un muro dibujado sobre un plano.

    Se modela como un EJE (polilínea o arco por 3 puntos) más un
    GROSOR físico en cm. El render lo pinta como polígono con hatch
    por material (estilo DIALux / Revit / AutoCAD Architecture): el
    usuario dibuja rápido con clics y el sistema le da volumen visual.

    Campos:
      * id — identificador local ("MU-001").
      * vertices — lista de puntos QPointF en pt PDF. Su interpretación
        depende de `tipo_geometria`:
          - LINEAL → polilínea de N ≥ 2 vértices ordenados.
          - ARCO   → exactamente 3 puntos de control:
              [inicio, punto por el que pasa el arco, fin].
      * cerrado — True si el primer y último vértice están conectados
        (solo tiene sentido en LINEAL con N ≥ 3).
      * material — TipoMaterialMuro. Determina cómo el motor de
        agrupación trata las trayectorias que lo cruzan y qué
        canalizaciones son válidas según NOM-001-SEDE.
      * tipo_geometria — TipoGeometriaMuro. LINEAL (default) o ARCO.
      * grosor_cm — grosor físico del muro en centímetros. 0.0
        significa "usa el default del material" (ver
        `GROSOR_DEFAULT_POR_MATERIAL`). Un valor positivo sobreescribe
        el default. El renderer lo aplica centrado sobre el eje.
    """
    id: str
    vertices: list[QPointF] = field(default_factory=list)
    cerrado: bool = False
    material: TipoMaterialMuro = TipoMaterialMuro.SIN_ESPECIFICAR
    tipo_geometria: TipoGeometriaMuro = TipoGeometriaMuro.LINEAL
    grosor_cm: float = 0.0
    justificacion: JustificacionMuro = JustificacionMuro.CENTRO

    def cantidad_vertices(self) -> int:
        return len(self.vertices)

    def material_legible(self) -> str:
        return MATERIAL_MURO_LABELS.get(self.material, str(self.material))

    def justificacion_legible(self) -> str:
        return JUSTIFICACION_MURO_LABELS.get(
            self.justificacion, str(self.justificacion),
        )

    def es_arco(self) -> bool:
        # Comparamos por NOMBRE en vez de identidad de enum para ser
        # robustos frente a doble import del módulo (`datos_proyecto`
        # cargado por dos rutas distintas crearía dos clases
        # `TipoGeometriaMuro` en memoria, y las identidades ARCO no
        # coincidirían aunque el nombre sí).
        nombre = getattr(self.tipo_geometria, "name", None)
        return nombre == "ARCO" and len(self.vertices) == 3

    def grosor_cm_efectivo(self) -> float:
        """Grosor efectivo en cm: si el usuario dejó 0, usa el default
        del material. Nunca regresa 0."""
        if self.grosor_cm > 0.0:
            return self.grosor_cm
        return GROSOR_DEFAULT_POR_MATERIAL.get(
            self.material, GROSOR_DEFAULT_POR_MATERIAL[
                TipoMaterialMuro.SIN_ESPECIFICAR
            ],
        )

    def grosor_pt(self, escala: Optional[EscalaCalibrada]) -> float:
        """Grosor convertido a pt PDF usando la escala calibrada.

        SIN escala calibrada, pt PDF y cm no tienen relación fija —
        el mismo plano puede estar a 1:50 o 1:200 y el ancho en pt
        cambia enormemente. En ese caso devolvemos un grosor visual
        FIJO y modesto (4 pt) para que el muro sea distinguible
        pero no dominante; al calibrar, todos los muros se
        redimensionan automáticamente a su grosor físico real."""
        cm = self.grosor_cm_efectivo()
        if escala is None:
            return 4.0   # placeholder visual pre-calibración
        m_por_pt = escala.m_por_pt
        if m_por_pt <= 0.0:
            return 4.0
        # cm × (m/cm) × (pt/m) = pt
        return (cm / 100.0) / m_por_pt


def puntos_arco_3(
    p1: QPointF, paso: QPointF, p2: QPointF, grados_por_tramo: float = 3.0,
) -> list[QPointF]:
    """Puntos de un arco que empieza en `p1`, pasa por `paso` y termina
    en `p2` (incluye p1 y p2), cada ~`grados_por_tramo` grados. Si los
    tres puntos están alineados devuelve la recta [p1, p2]."""
    ax, ay, bx, by, cx, cy = p1.x(), p1.y(), paso.x(), paso.y(), p2.x(), p2.y()
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-9:
        return [QPointF(p1), QPointF(p2)]
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay)
          + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx)
          + (cx * cx + cy * cy) * (bx - ax)) / d
    r = math.hypot(ax - ux, ay - uy)
    a1 = math.atan2(ay - uy, ax - ux)
    am = math.atan2(by - uy, bx - ux)
    a2 = math.atan2(cy - uy, cx - ux)
    # Sentido: el que pasa por `paso`.
    dos_pi = 2.0 * math.pi
    ccw_total = (a2 - a1) % dos_pi
    ccw_medio = (am - a1) % dos_pi
    barrido = ccw_total if ccw_medio < ccw_total else ccw_total - dos_pi
    n = max(2, int(math.ceil(abs(math.degrees(barrido)) / grados_por_tramo)))
    pts = [QPointF(p1)]
    for k in range(1, n):
        a = a1 + barrido * k / n
        pts.append(QPointF(ux + r * math.cos(a), uy + r * math.sin(a)))
    pts.append(QPointF(p2))
    return pts


@dataclass
class Habitacion:
    """Una habitación: polígono cerrado con nombre, tipo de uso, y
    área calculada.

    Los vértices definen el contorno en pt PDF. El área en m² se
    computa con la escala calibrada del plano al que pertenece.

    Campos:
      * id — identificador local ("HB-001").
      * nombre — texto libre ("Baño principal", "Recámara 2"...).
      * vertices — lista de puntos QPointF que definen el polígono
        (mínimo 3). Siempre implícitamente cerrado.
      * tipo_uso — TipoUsoHabitacion. Categoría funcional del espacio,
        usada por el motor de agrupación NOM-001, cálculo de
        densidad de carga y reportes.
      * arcos — tramos curvos del contorno: {i: punto de paso}. El tramo
        que va del vértice i al siguiente es un arco que pasa por ese
        punto. Los tramos que no aparecen son rectos. Para cualquier
        cálculo de área, contención, etc. usar `poligono()`, que ya trae
        los arcos convertidos en puntos.
    """
    id: str
    nombre: str
    vertices: list[QPointF] = field(default_factory=list)
    tipo_uso: TipoUsoHabitacion = TipoUsoHabitacion.OTRO
    arcos: dict[int, QPointF] = field(default_factory=dict)

    def poligono(self, grados_por_tramo: float = 3.0) -> list[QPointF]:
        """Contorno completo como polígono: vértices + los arcos
        muestreados. Sin arcos es igual a `vertices`."""
        n = len(self.vertices)
        if not self.arcos or n < 2:
            return [QPointF(v) for v in self.vertices]
        pts: list[QPointF] = []
        for i in range(n):
            a, b = self.vertices[i], self.vertices[(i + 1) % n]
            paso = self.arcos.get(i)
            if paso is None:
                pts.append(QPointF(a))
            else:
                pts.extend(puntos_arco_3(a, paso, b, grados_por_tramo)[:-1])
        return pts

    def cantidad_vertices(self) -> int:
        return len(self.vertices)

    def tipo_uso_legible(self) -> str:
        return USO_HABITACION_LABELS.get(self.tipo_uso, str(self.tipo_uso))

    def area_pt2(self) -> float:
        """Área del polígono en pt² del PDF (fórmula del shoelace).

        Devuelve valor absoluto — el sentido del recorrido (horario o
        antihorario) no importa.
        """
        pts = self.poligono(grados_por_tramo=0.5)
        n = len(pts)
        if n < 3:
            return 0.0
        acc = 0.0
        for i in range(n):
            x1, y1 = pts[i].x(), pts[i].y()
            x2, y2 = pts[(i + 1) % n].x(), pts[(i + 1) % n].y()
            acc += x1 * y2 - x2 * y1
        return abs(acc) / 2.0

    def area_m2(self, escala: Optional[EscalaCalibrada]) -> Optional[float]:
        """Área en m². Requiere escala calibrada; devuelve None si no
        hay escala."""
        if escala is None:
            return None
        f = escala.m_por_pt
        # pt² × (m/pt)² = m²
        return self.area_pt2() * f * f


# ---------------------------------------------------------------------------
# Puerta y Ventana (aberturas ancladas a un muro)
# ---------------------------------------------------------------------------

class SentidoAperturaPuerta(Enum):
    """Sentido de barrido del arco de apertura de la puerta.

    * IZQ — la hoja gira hacia el lado izquierdo (mirando en el sentido
      de recorrido del muro).
    * DER — la hoja gira hacia el lado derecho.
    * NINGUNO — no dibujar arco (puerta corrediza, sin hoja, hueco puro).
    """
    IZQ     = "izq"
    DER     = "der"
    NINGUNO = "ninguno"


@dataclass
class Puerta:
    """Puerta como abertura anclada a un muro.

    La posición se guarda como la distancia acumulada desde el vértice
    inicial del muro (recorriendo la polilínea/arco). El motor de
    delimitación puede calcular el punto 2D en cualquier momento a
    partir del muro + esta distancia. Así, al mover un vértice del
    muro la puerta se acomoda de forma natural sin depender de
    coordenadas absolutas que se desincronicen.

    Campos:
      * id — identificador local ("PU-001").
      * muro_id — muro al que está anclada.
      * d_desde_inicio_pt — distancia acumulada desde el vértice inicial
        del muro hasta el centro de la puerta (pt PDF).
      * ancho_pt — ancho del hueco de la puerta (pt PDF). Al calibrar
        el plano equivale a un ancho físico (0.90 m típico).
      * sentido_apertura — SentidoAperturaPuerta. Determina hacia qué
        lado del muro se dibuja el arco de barrido de la hoja.
      * pivote_en_inicio — dice en qué extremo del hueco está la
        bisagra: True = extremo del lado de menor `d_desde_inicio` a
        lo largo del muro (extremo A). False = extremo del lado de
        mayor `d_desde_inicio` (extremo B). Junto con sentido_apertura
        define las 4 orientaciones posibles del arco.
    """
    id: str
    muro_id: str
    d_desde_inicio_pt: float
    ancho_pt: float
    sentido_apertura: SentidoAperturaPuerta = SentidoAperturaPuerta.DER
    pivote_en_inicio: bool = True


@dataclass
class Ventana:
    """Ventana como abertura anclada a un muro.

    Igual que Puerta pero con dos dimensiones verticales adicionales
    (altura desde piso + alto de la ventana), útiles para el motor
    eléctrico (los contactos no van bajo ventana; se prefieren
    circuitos de iluminación con salida encima).

    Campos:
      * id — identificador local ("VE-001").
      * muro_id — muro al que está anclada.
      * d_desde_inicio_pt — distancia acumulada desde el vértice inicial
        del muro hasta el centro de la ventana (pt PDF).
      * ancho_pt — ancho del hueco de la ventana (pt PDF).
      * alto_m — altura vertical de la ventana en metros (0.30 mínimo
        para ventilas, ~1.20 típico en recámaras).
      * altura_piso_m — altura desde el piso al alfeizar (parte
        inferior de la ventana) en metros. ~1.00 típico.
    """
    id: str
    muro_id: str
    d_desde_inicio_pt: float
    ancho_pt: float
    alto_m: float = 1.20
    altura_piso_m: float = 1.00


# ---------------------------------------------------------------------------
# PlanoDeProyecto
# ---------------------------------------------------------------------------

# Ancho del thumbnail generado al cargar un plano. Suficiente para verse
# nítido en las cards de 240 px de ancho del panel lateral.
_ANCHO_THUMBNAIL_PX = 150


@dataclass
class PlanoDeProyecto:
    """Un plano cargado en el proyecto.

    Campos:
      * id — identificador local (ej. "PL-001").
      * titulo — nombre del plano, ingresado por el usuario.
      * path — ruta absoluta al archivo PDF/PNG/JPG.
      * escala — EscalaCalibrada aplicada a este plano, o None si aún
        no está calibrado.
      * fecha_carga — string legible con la fecha de carga.
      * thumbnail — QPixmap cacheado, generado al cargar.
      * muros — lista de Muro dibujados sobre este plano (Sesión D).
      * habitaciones — lista de Habitacion dibujadas sobre este plano
        (Sesión D). Cada habitación tiene sus vértices en pt PDF.
      * puertas — lista de Puerta ancladas a muros de este plano
        (Sesión D.2).
      * ventanas — lista de Ventana ancladas a muros de este plano
        (Sesión D.2).
    """
    id: str
    titulo: str
    path: Path
    escala: Optional[EscalaCalibrada] = None
    fecha_carga: str = ""
    thumbnail: Optional[QPixmap] = None
    muros: list[Muro] = field(default_factory=list)
    habitaciones: list[Habitacion] = field(default_factory=list)
    puertas: list[Puerta] = field(default_factory=list)
    ventanas: list[Ventana] = field(default_factory=list)

    def esta_calibrado(self) -> bool:
        return self.escala is not None

    def existe_archivo(self) -> bool:
        try:
            return self.path.exists()
        except Exception:  # noqa: BLE001
            return False


# ---------------------------------------------------------------------------
# ProyectoAbierto
# ---------------------------------------------------------------------------

class ProyectoAbierto(QObject):
    """Modelo en memoria de un proyecto abierto en su espacio de trabajo.

    Encapsula:
      * Metadata del proyecto (dict que viene del wizard/BD).
      * Lista ordenada de planos cargados.
      * (Futuro — placeholders para) elementos, tableros, canalizaciones,
        propuestas del motor.

    Todo cambio pasa por métodos públicos que emiten signals; la UI
    reacciona a esos signals para actualizarse. Los tests y la
    integración con SQLite pueden reemplazar internamente los métodos
    sin cambiar la API pública.

    Signals:
      * plano_agregado(PlanoDeProyecto)
      * plano_eliminado(str)
      * plano_actualizado(PlanoDeProyecto)  # cambió título u otros
      * escala_actualizada(str, object)      # (plano_id, EscalaCalibrada o None)
    """

    plano_agregado     = pyqtSignal(object)  # PlanoDeProyecto
    plano_eliminado    = pyqtSignal(str)     # id del plano eliminado
    plano_actualizado  = pyqtSignal(object)  # PlanoDeProyecto
    escala_actualizada = pyqtSignal(str, object)  # (plano_id, EscalaCalibrada|None)

    # Sesión D — Delimitación
    muro_agregado       = pyqtSignal(str, object)  # (plano_id, Muro)
    muro_actualizado    = pyqtSignal(str, object)  # (plano_id, Muro)
    muro_eliminado      = pyqtSignal(str, str)     # (plano_id, muro_id)
    habitacion_agregada    = pyqtSignal(str, object)  # (plano_id, Habitacion)
    habitacion_actualizada = pyqtSignal(str, object)  # (plano_id, Habitacion)
    habitacion_eliminada   = pyqtSignal(str, str)     # (plano_id, hab_id)

    # Sesión D.2 — Aberturas
    puerta_agregada     = pyqtSignal(str, object)  # (plano_id, Puerta)
    puerta_actualizada  = pyqtSignal(str, object)  # (plano_id, Puerta)
    puerta_eliminada    = pyqtSignal(str, str)     # (plano_id, puerta_id)
    ventana_agregada    = pyqtSignal(str, object)  # (plano_id, Ventana)
    ventana_actualizada = pyqtSignal(str, object)  # (plano_id, Ventana)
    ventana_eliminada   = pyqtSignal(str, str)     # (plano_id, ventana_id)

    # Plano actualmente activo (compartido entre etapas Planos, Delimitación,
    # Elementos, Tableros...). Emitido al cambiar. None si no hay ninguno.
    plano_activo_cambiado = pyqtSignal(object)  # id: str o None

    def __init__(self, datos: dict, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._datos: dict = dict(datos)
        self._planos: list[PlanoDeProyecto] = []
        self._contador_planos: int = 0
        self._contador_muros: int = 0
        self._contador_habs: int = 0
        self._contador_puertas: int = 0
        self._contador_ventanas: int = 0
        # Plano activo compartido entre las etapas del espacio de
        # trabajo: cuando la etapa Planos lo cambia, Delimitación y
        # las siguientes lo escuchan y refrescan su canvas.
        self._plano_activo_id: Optional[str] = None

    # -------------------------------------------- metadata del proyecto

    @property
    def id(self) -> str:
        return str(self._datos.get("id", ""))

    @property
    def nombre(self) -> str:
        return str(self._datos.get("nombre", "Proyecto"))

    @property
    def cliente(self) -> str:
        return str(self._datos.get("cliente", ""))

    @property
    def tipo(self) -> str:
        return str(self._datos.get("tipo", ""))

    @property
    def subtipo(self) -> str:
        return str(self._datos.get("subtipo", ""))

    @property
    def estado(self) -> str:
        return str(self._datos.get("estado", "borrador"))

    def datos_crudos(self) -> dict:
        """Devuelve una COPIA del dict de metadata original (para
        pasarlo a componentes que aún trabajan con dicts, como el
        header de EspacioTrabajoProyecto)."""
        return dict(self._datos)

    # ----------------------------------------------------- planos: consulta

    def planos(self) -> list[PlanoDeProyecto]:
        """Lista de planos en el orden en que fueron agregados. Copia
        superficial, para que la UI no mute el interno."""
        return list(self._planos)

    def plano_por_id(self, plano_id: str) -> Optional[PlanoDeProyecto]:
        return next((p for p in self._planos if p.id == plano_id), None)

    def cantidad_planos(self) -> int:
        return len(self._planos)

    def plano_activo_id(self) -> Optional[str]:
        return self._plano_activo_id

    def plano_activo(self) -> Optional[PlanoDeProyecto]:
        pid = self._plano_activo_id
        return self.plano_por_id(pid) if pid else None

    def set_plano_activo(self, plano_id: Optional[str]) -> None:
        """Cambia el plano actualmente activo. Emite
        `plano_activo_cambiado(id)`. Pasa None para "ninguno"."""
        if plano_id == self._plano_activo_id:
            return
        if plano_id is not None and self.plano_por_id(plano_id) is None:
            return
        self._plano_activo_id = plano_id
        self.plano_activo_cambiado.emit(plano_id)

    # -------------------------------------------------- planos: mutación

    def agregar_plano(
        self,
        titulo: str,
        path: str | Path,
    ) -> PlanoDeProyecto:
        """Crea y agrega un PlanoDeProyecto al proyecto. Genera el
        thumbnail sincrónicamente (rápido — ~50-200 ms según el
        tamaño del PDF). Emite `plano_agregado`.

        Lanza ValueError si el título está vacío o el archivo no existe.
        """
        titulo = (titulo or "").strip()
        if not titulo:
            raise ValueError("El título del plano no puede estar vacío.")
        p = Path(path)
        if not p.exists():
            raise ValueError(f"El archivo no existe:\n{p}")

        self._contador_planos += 1
        plano = PlanoDeProyecto(
            id=f"PL-{self._contador_planos:03d}",
            titulo=titulo,
            path=p,
            escala=None,
            fecha_carga=datetime.now().strftime("%d %b %Y"),
            thumbnail=_generar_thumbnail(p),
        )
        self._planos.append(plano)
        self.plano_agregado.emit(plano)
        return plano

    def eliminar_plano(self, plano_id: str) -> bool:
        plano = self.plano_por_id(plano_id)
        if plano is None:
            return False
        self._planos.remove(plano)
        self.plano_eliminado.emit(plano_id)
        return True

    def renombrar_plano(self, plano_id: str, nuevo_titulo: str) -> bool:
        nuevo_titulo = (nuevo_titulo or "").strip()
        if not nuevo_titulo:
            return False
        plano = self.plano_por_id(plano_id)
        if plano is None:
            return False
        if plano.titulo == nuevo_titulo:
            return True  # nada que hacer
        plano.titulo = nuevo_titulo
        self.plano_actualizado.emit(plano)
        return True

    def actualizar_escala(
        self,
        plano_id: str,
        escala: Optional[EscalaCalibrada],
    ) -> bool:
        """Aplica (o quita, si es None) la escala calibrada de un
        plano. Emite `escala_actualizada`."""
        plano = self.plano_por_id(plano_id)
        if plano is None:
            return False
        if plano.escala == escala:
            return True
        plano.escala = escala
        self.escala_actualizada.emit(plano_id, escala)
        return True

    # ------------------------------------------- muros: consulta y mutación

    def agregar_muro(
        self,
        plano_id: str,
        vertices: list[QPointF],
        cerrado: bool = False,
        material: TipoMaterialMuro = TipoMaterialMuro.SIN_ESPECIFICAR,
        tipo_geometria: TipoGeometriaMuro = TipoGeometriaMuro.LINEAL,
        grosor_cm: float = 0.0,
        justificacion: JustificacionMuro = JustificacionMuro.CENTRO,
    ) -> Optional[Muro]:
        plano = self.plano_por_id(plano_id)
        if plano is None:
            return None
        # Validación de cantidad de vértices según el tipo de geometría.
        # Comparamos por NOMBRE del enum para tolerar doble import.
        _es_arco = getattr(tipo_geometria, "name", None) == "ARCO"
        if _es_arco:
            if len(vertices) != 3:
                return None
        else:
            if len(vertices) < 2:
                return None
        self._contador_muros += 1
        muro = Muro(
            id=f"MU-{self._contador_muros:03d}",
            vertices=[QPointF(p) for p in vertices],
            cerrado=cerrado,
            material=material,
            tipo_geometria=tipo_geometria,
            grosor_cm=max(0.0, float(grosor_cm)),
            justificacion=justificacion,
        )
        plano.muros.append(muro)
        self.muro_agregado.emit(plano_id, muro)
        return muro

    def actualizar_justificacion_muro(
        self, plano_id: str, muro_id: str, justificacion: JustificacionMuro,
    ) -> bool:
        plano = self.plano_por_id(plano_id)
        if plano is None:
            return False
        for m in plano.muros:
            if m.id == muro_id:
                if m.justificacion == justificacion:
                    return True
                m.justificacion = justificacion
                self.muro_actualizado.emit(plano_id, m)
                return True
        return False

    def actualizar_material_muro(
        self, plano_id: str, muro_id: str, material: TipoMaterialMuro,
    ) -> bool:
        plano = self.plano_por_id(plano_id)
        if plano is None:
            return False
        for m in plano.muros:
            if m.id == muro_id:
                if m.material == material:
                    return True
                m.material = material
                self.muro_actualizado.emit(plano_id, m)
                return True
        return False

    def actualizar_grosor_muro(
        self, plano_id: str, muro_id: str, grosor_cm: float,
    ) -> bool:
        plano = self.plano_por_id(plano_id)
        if plano is None:
            return False
        nuevo = max(0.0, float(grosor_cm))
        for m in plano.muros:
            if m.id == muro_id:
                if abs(m.grosor_cm - nuevo) < 1e-6:
                    return True
                m.grosor_cm = nuevo
                self.muro_actualizado.emit(plano_id, m)
                return True
        return False

    def actualizar_muro(self, plano_id: str, muro: Muro) -> bool:
        """Notifica que el muro cambió (por ejemplo, se movió un
        vértice). El objeto Muro se muta en sitio; este método solo
        emite la señal para que el UI se refresque."""
        plano = self.plano_por_id(plano_id)
        if plano is None or muro not in plano.muros:
            return False
        self.muro_actualizado.emit(plano_id, muro)
        return True

    def eliminar_muro(self, plano_id: str, muro_id: str) -> bool:
        """Elimina un muro y, en cascada, todas las puertas/ventanas
        que estaban ancladas a él (ya no tienen sentido sin muro)."""
        plano = self.plano_por_id(plano_id)
        if plano is None:
            return False
        for m in plano.muros:
            if m.id == muro_id:
                # Jerarquía: primero lo que cuelga del muro (puertas y
                # ventanas), con el muro todavía presente para que la
                # vista pueda ubicarlas al quitarlas; al final, el muro.
                huerfanas_p = [p for p in plano.puertas if p.muro_id == muro_id]
                for p in huerfanas_p:
                    plano.puertas.remove(p)
                    self.puerta_eliminada.emit(plano_id, p.id)
                huerfanas_v = [v for v in plano.ventanas if v.muro_id == muro_id]
                for v in huerfanas_v:
                    plano.ventanas.remove(v)
                    self.ventana_eliminada.emit(plano_id, v.id)
                plano.muros.remove(m)
                self.muro_eliminado.emit(plano_id, muro_id)
                return True
        return False

    def borrar_muros(self, plano_id: str) -> int:
        """Borra todos los muros del plano y en cascada todas sus
        puertas/ventanas (nada queda anclado a un muro inexistente)."""
        plano = self.plano_por_id(plano_id)
        if plano is None:
            return 0
        ids_muros = [m.id for m in plano.muros]
        ids_puertas = [p.id for p in plano.puertas]
        ids_ventanas = [v.id for v in plano.ventanas]
        plano.muros.clear()
        plano.puertas.clear()
        plano.ventanas.clear()
        for pid in ids_puertas:
            self.puerta_eliminada.emit(plano_id, pid)
        for vid in ids_ventanas:
            self.ventana_eliminada.emit(plano_id, vid)
        for mid in ids_muros:
            self.muro_eliminado.emit(plano_id, mid)
        return len(ids_muros)

    # -------------------------------------- habitaciones: consulta y mutación

    def agregar_habitacion(
        self,
        plano_id: str,
        nombre: str,
        vertices: list[QPointF],
        tipo_uso: TipoUsoHabitacion = TipoUsoHabitacion.OTRO,
        arcos: Optional[dict[int, QPointF]] = None,
    ) -> Optional[Habitacion]:
        plano = self.plano_por_id(plano_id)
        nombre = (nombre or "").strip()
        # Con arcos bastan 2 vértices (p. ej. dos semicírculos).
        minimo = 2 if arcos else 3
        if plano is None or len(vertices) < minimo or not nombre:
            return None
        self._contador_habs += 1
        hab = Habitacion(
            id=f"HB-{self._contador_habs:03d}",
            nombre=nombre,
            vertices=[QPointF(p) for p in vertices],
            tipo_uso=tipo_uso,
            arcos={int(i): QPointF(p) for i, p in (arcos or {}).items()},
        )
        plano.habitaciones.append(hab)
        self.habitacion_agregada.emit(plano_id, hab)
        return hab

    def actualizar_tipo_uso_habitacion(
        self, plano_id: str, hab_id: str, tipo_uso: TipoUsoHabitacion,
    ) -> bool:
        plano = self.plano_por_id(plano_id)
        if plano is None:
            return False
        for h in plano.habitaciones:
            if h.id == hab_id:
                if h.tipo_uso == tipo_uso:
                    return True
                h.tipo_uso = tipo_uso
                self.habitacion_actualizada.emit(plano_id, h)
                return True
        return False

    def actualizar_habitacion(self, plano_id: str, hab: Habitacion) -> bool:
        plano = self.plano_por_id(plano_id)
        if plano is None or hab not in plano.habitaciones:
            return False
        self.habitacion_actualizada.emit(plano_id, hab)
        return True

    def renombrar_habitacion(
        self, plano_id: str, hab_id: str, nuevo_nombre: str,
    ) -> bool:
        nuevo_nombre = (nuevo_nombre or "").strip()
        if not nuevo_nombre:
            return False
        plano = self.plano_por_id(plano_id)
        if plano is None:
            return False
        for h in plano.habitaciones:
            if h.id == hab_id:
                if h.nombre == nuevo_nombre:
                    return True
                h.nombre = nuevo_nombre
                self.habitacion_actualizada.emit(plano_id, h)
                return True
        return False

    def eliminar_habitacion(self, plano_id: str, hab_id: str) -> bool:
        plano = self.plano_por_id(plano_id)
        if plano is None:
            return False
        for h in plano.habitaciones:
            if h.id == hab_id:
                plano.habitaciones.remove(h)
                self.habitacion_eliminada.emit(plano_id, hab_id)
                return True
        return False

    def borrar_habitaciones(self, plano_id: str) -> int:
        plano = self.plano_por_id(plano_id)
        if plano is None:
            return 0
        ids = [h.id for h in plano.habitaciones]
        plano.habitaciones.clear()
        for hid in ids:
            self.habitacion_eliminada.emit(plano_id, hid)
        return len(ids)

    # -------------------------------------------- puertas: consulta y mutación

    def agregar_puerta(
        self,
        plano_id: str,
        muro_id: str,
        d_desde_inicio_pt: float,
        ancho_pt: float,
        sentido: SentidoAperturaPuerta = SentidoAperturaPuerta.DER,
        pivote_en_inicio: bool = True,
    ) -> Optional[Puerta]:
        plano = self.plano_por_id(plano_id)
        if plano is None:
            return None
        # Verificar que el muro existe
        if not any(m.id == muro_id for m in plano.muros):
            return None
        if ancho_pt <= 0.0:
            return None
        self._contador_puertas += 1
        puerta = Puerta(
            id=f"PU-{self._contador_puertas:03d}",
            muro_id=muro_id,
            d_desde_inicio_pt=float(d_desde_inicio_pt),
            ancho_pt=float(ancho_pt),
            sentido_apertura=sentido,
            pivote_en_inicio=bool(pivote_en_inicio),
        )
        plano.puertas.append(puerta)
        self.puerta_agregada.emit(plano_id, puerta)
        return puerta

    def actualizar_puerta(self, plano_id: str, puerta: Puerta) -> bool:
        plano = self.plano_por_id(plano_id)
        if plano is None or puerta not in plano.puertas:
            return False
        self.puerta_actualizada.emit(plano_id, puerta)
        return True

    def invertir_sentido_puerta(self, plano_id: str, puerta_id: str) -> bool:
        """Alterna el sentido de apertura entre IZQ y DER (o quita el
        arco si estaba en NINGUNO). Emite `puerta_actualizada`."""
        plano = self.plano_por_id(plano_id)
        if plano is None:
            return False
        for p in plano.puertas:
            if p.id == puerta_id:
                if p.sentido_apertura == SentidoAperturaPuerta.DER:
                    p.sentido_apertura = SentidoAperturaPuerta.IZQ
                elif p.sentido_apertura == SentidoAperturaPuerta.IZQ:
                    p.sentido_apertura = SentidoAperturaPuerta.DER
                else:
                    p.sentido_apertura = SentidoAperturaPuerta.DER
                self.puerta_actualizada.emit(plano_id, p)
                return True
        return False

    def eliminar_puerta(self, plano_id: str, puerta_id: str) -> bool:
        plano = self.plano_por_id(plano_id)
        if plano is None:
            return False
        for p in plano.puertas:
            if p.id == puerta_id:
                plano.puertas.remove(p)
                self.puerta_eliminada.emit(plano_id, puerta_id)
                return True
        return False

    def puertas_de_muro(
        self, plano_id: str, muro_id: str,
    ) -> list[Puerta]:
        plano = self.plano_por_id(plano_id)
        if plano is None:
            return []
        return [p for p in plano.puertas if p.muro_id == muro_id]

    # ------------------------------------------- ventanas: consulta y mutación

    def agregar_ventana(
        self,
        plano_id: str,
        muro_id: str,
        d_desde_inicio_pt: float,
        ancho_pt: float,
        alto_m: float = 1.20,
        altura_piso_m: float = 1.00,
    ) -> Optional[Ventana]:
        plano = self.plano_por_id(plano_id)
        if plano is None:
            return None
        if not any(m.id == muro_id for m in plano.muros):
            return None
        if ancho_pt <= 0.0:
            return None
        self._contador_ventanas += 1
        ventana = Ventana(
            id=f"VE-{self._contador_ventanas:03d}",
            muro_id=muro_id,
            d_desde_inicio_pt=float(d_desde_inicio_pt),
            ancho_pt=float(ancho_pt),
            alto_m=max(0.0, float(alto_m)),
            altura_piso_m=max(0.0, float(altura_piso_m)),
        )
        plano.ventanas.append(ventana)
        self.ventana_agregada.emit(plano_id, ventana)
        return ventana

    def actualizar_ventana(self, plano_id: str, ventana: Ventana) -> bool:
        plano = self.plano_por_id(plano_id)
        if plano is None or ventana not in plano.ventanas:
            return False
        self.ventana_actualizada.emit(plano_id, ventana)
        return True

    def eliminar_ventana(self, plano_id: str, ventana_id: str) -> bool:
        plano = self.plano_por_id(plano_id)
        if plano is None:
            return False
        for v in plano.ventanas:
            if v.id == ventana_id:
                plano.ventanas.remove(v)
                self.ventana_eliminada.emit(plano_id, ventana_id)
                return True
        return False

    def ventanas_de_muro(
        self, plano_id: str, muro_id: str,
    ) -> list[Ventana]:
        plano = self.plano_por_id(plano_id)
        if plano is None:
            return []
        return [v for v in plano.ventanas if v.muro_id == muro_id]


# ---------------------------------------------------------------------------
# Helpers de thumbnail — factorizados aquí para poder reusarlos desde el UI
# ---------------------------------------------------------------------------

def _generar_thumbnail(path: Path) -> Optional[QPixmap]:
    """Genera un thumbnail del plano (PDF o imagen). Devuelve None si
    falla o si el formato no está soportado.

    Para PDF: renderiza la 1ra página a un factor calculado para que
    el ancho salga ≈ _ANCHO_THUMBNAIL_PX (rápido — <200 ms).
    Para imagen: carga y escala.
    """
    try:
        ext = path.suffix.lower()
        if ext == ".pdf":
            return _thumbnail_pdf(path)
        if ext in {".png", ".jpg", ".jpeg", ".bmp"}:
            return _thumbnail_imagen(path)
        return None
    except Exception:  # noqa: BLE001
        return None


def _thumbnail_pdf(path: Path) -> Optional[QPixmap]:
    if not _PYMUPDF_OK:
        return None
    doc = fitz.open(str(path))
    try:
        if doc.page_count == 0:
            return None
        page = doc.load_page(0)
        w = float(page.rect.width) if page.rect.width > 0 else 1.0
        factor = _ANCHO_THUMBNAIL_PX / w
        matriz = fitz.Matrix(factor, factor)
        pix = page.get_pixmap(matrix=matriz, alpha=False)
        image = QImage(
            pix.samples, pix.width, pix.height, pix.stride,
            QImage.Format.Format_RGB888,
        ).copy()
        return QPixmap.fromImage(image)
    finally:
        doc.close()


def _thumbnail_imagen(path: Path) -> Optional[QPixmap]:
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return None
    return pixmap.scaledToWidth(
        _ANCHO_THUMBNAIL_PX, Qt.TransformationMode.SmoothTransformation
    )
