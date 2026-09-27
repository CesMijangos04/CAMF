# calculos_electricos.py
"""
Motor de cálculos eléctricos según NOM-001-SEDE-2012.
 
Tablas implementadas:
  - 310-15(B)(16): Ampacidades en canalización (cobre y aluminio, 60/75/90°C)
  - 310-15(B)(2)(a): Factor de corrección por temperatura ambiente
  - 310-15(B)(3)(a): Factor de corrección por agrupamiento de conductores
  - 250-122: Calibre mínimo del conductor de puesta a tierra
  - Cap. 9 Tabla 9 NEC: Resistencias y reactancias para caída de tensión
 
Convenciones:
  - Funciones puras (no estado, no BD).
  - SI: Watts, Amperes, Volts, metros.
  - Devuelven None si no hay datos suficientes.
"""
 
from math import sqrt
from typing import Optional, Dict, List
 
SQRT3 = sqrt(3)
 
# Temperatura ambiente estándar para México (30°C → factor 1.0)
TEMP_AMBIENTE_DEFAULT_C = 30
 
 
# ════════════════════════════════════════════════════════════════════
# TABLA 310-15(B)(16) — AMPACIDADES (canalización)
# Valores oficiales NOM-001-SEDE-2012
# ════════════════════════════════════════════════════════════════════
 
# COBRE
AMPACIDAD_COBRE = {
    # calibre:    (60°C TW, 75°C THW/THHN, 90°C THHN)
    "14 AWG":     (15,  20,  25),
    "12 AWG":     (20,  25,  30),
    "10 AWG":     (30,  35,  40),
    "8 AWG":      (40,  50,  55),
    "6 AWG":      (55,  65,  75),
    "4 AWG":      (70,  85,  95),
    "3 AWG":      (85, 100, 115),
    "2 AWG":      (95, 115, 130),
    "1 AWG":     (110, 130, 145),
    "1/0 AWG":   (125, 150, 170),
    "2/0 AWG":   (145, 175, 195),
    "3/0 AWG":   (165, 200, 225),
    "4/0 AWG":   (195, 230, 260),
    "250 KCM":   (215, 255, 290),
    "300 KCM":   (240, 285, 320),
    "350 KCM":   (260, 310, 350),
    "400 KCM":   (280, 335, 380),
    "500 KCM":   (320, 380, 430),
    "600 KCM":   (355, 420, 475),
    "700 KCM":   (385, 460, 520),
    "750 KCM":   (400, 475, 535),
    "800 KCM":   (410, 490, 555),
    "900 KCM":   (435, 520, 585),
    "1000 KCM":  (455, 545, 615),
    "1250 KCM":  (495, 590, 665),
    "1500 KCM":  (525, 625, 705),
    "1750 KCM":  (545, 650, 735),
    "2000 KCM":  (555, 665, 750),
}
 
# ALUMINIO
AMPACIDAD_ALUMINIO = {
    "12 AWG":     (15,  20,  25),
    "10 AWG":     (25,  30,  35),
    "8 AWG":      (30,  40,  45),
    "6 AWG":      (40,  50,  60),
    "4 AWG":      (55,  65,  75),
    "3 AWG":      (65,  75,  85),
    "2 AWG":      (75,  90, 100),
    "1 AWG":      (85, 100, 115),
    "1/0 AWG":   (100, 120, 135),
    "2/0 AWG":   (115, 135, 150),
    "3/0 AWG":   (130, 155, 175),
    "4/0 AWG":   (150, 180, 205),
    "250 KCM":   (170, 205, 230),
    "300 KCM":   (190, 230, 260),
    "350 KCM":   (210, 250, 280),
    "400 KCM":   (225, 270, 305),
    "500 KCM":   (260, 310, 350),
    "600 KCM":   (285, 340, 385),
    "700 KCM":   (310, 375, 420),
    "750 KCM":   (320, 385, 435),
    "800 KCM":   (330, 395, 450),
    "900 KCM":   (355, 425, 480),
    "1000 KCM":  (375, 445, 500),
    "1250 KCM":  (405, 485, 545),
    "1500 KCM":  (435, 520, 585),
    "1750 KCM":  (455, 545, 615),
    "2000 KCM":  (470, 560, 630),
}
 
 
# ════════════════════════════════════════════════════════════════════
# TABLA 310-15(B)(2)(a) — FACTOR DE CORRECCIÓN POR TEMPERATURA
# Para temperatura ambiente del lugar donde corre el cable
# ════════════════════════════════════════════════════════════════════
 
# (temp_min, temp_max): {60°C: factor, 75°C: factor, 90°C: factor}
FACTOR_TEMPERATURA = [
    # (T amb °C, F60, F75, F90)
    (10, 1.29, 1.20, 1.15),
    (15, 1.22, 1.15, 1.12),
    (20, 1.15, 1.11, 1.08),
    (25, 1.08, 1.05, 1.04),
    (30, 1.00, 1.00, 1.00),
    (35, 0.91, 0.94, 0.96),
    (40, 0.82, 0.88, 0.91),
    (45, 0.71, 0.82, 0.87),
    (50, 0.58, 0.75, 0.82),
    (55, 0.41, 0.67, 0.76),
    (60, 0.00, 0.58, 0.71),
    (65, 0.00, 0.47, 0.65),
    (70, 0.00, 0.33, 0.58),
    (75, 0.00, 0.00, 0.50),
    (80, 0.00, 0.00, 0.41),
]
 
 
def factor_correccion_temperatura(temp_ambiente_c: float = TEMP_AMBIENTE_DEFAULT_C,
                                   aislamiento_c: int = 75) -> float:
    """
    Devuelve el factor de corrección por temperatura ambiente.
    Si temp_ambiente_c <= 30, devuelve 1.0.
    Usa el rango más cercano de la tabla.
    """
    if aislamiento_c not in (60, 75, 90):
        aislamiento_c = 75
    idx_col = {60: 1, 75: 2, 90: 3}[aislamiento_c]
 
    # Buscar el rango más alto cuya T_amb es <= temp_ambiente_c
    factor = 1.0
    for fila in FACTOR_TEMPERATURA:
        if temp_ambiente_c >= fila[0]:
            factor = fila[idx_col]
    return factor
 
 
# ════════════════════════════════════════════════════════════════════
# TABLA 310-15(B)(3)(a) — FACTOR DE AGRUPAMIENTO
# Cuando hay varios circuitos en la misma canalización
# ════════════════════════════════════════════════════════════════════
 
# (num_conductores_activos, factor)
FACTOR_AGRUPAMIENTO = [
    (3,   1.00),  # 1 a 3 conductores: sin reducción
    (6,   0.80),  # 4 a 6
    (9,   0.70),  # 7 a 9
    (20,  0.50),  # 10 a 20
    (30,  0.45),  # 21 a 30
    (40,  0.40),  # 31 a 40
    (999, 0.35),  # >40
]
 
 
def factor_correccion_agrupamiento(num_conductores_activos: int = 3) -> float:
    """
    Factor por agrupamiento de conductores activos en una canalización.
    Hasta 3 conductores: 1.0 (sin reducción).
    """
    if num_conductores_activos <= 0:
        return 1.0
    for limite, factor in FACTOR_AGRUPAMIENTO:
        if num_conductores_activos <= limite:
            return factor
    return 0.35
 
 
def aislamiento_segun_itm(amperaje_itm) -> int:
    """
    Regla NEC 110.14(C) / NOM-001:
      - ITM ≤ 100 A → diseñar con columna 60°C
      - ITM > 100 A → diseñar con columna 75°C
 
    El cable físico puede ser THHN (90°C), pero para el cálculo de ampacidad
    se usa la columna que limita el terminal del interruptor.
    """
    if not amperaje_itm:
        return 75  # default razonable cuando no hay ITM definido
    try:
        amp = float(amperaje_itm)
    except (ValueError, TypeError):
        return 75
    return 60 if amp <= 100 else 75
 
 
def conductores_activos_circuito(polos: int) -> int:
    """
    Conductores que llevan corriente en un circuito (sin neutro balanceado).
    - Monofásico: 2 (1F + N)
    - Bifásico: 2 (2F)
    - Trifásico balanceado: 3 (3F, N no cuenta)
    """
    if polos == 1:
        return 2
    elif polos == 2:
        return 2
    elif polos == 3:
        return 3
    return polos
 
 
# ════════════════════════════════════════════════════════════════════
# TABLA 250-122 — CALIBRE DEL CONDUCTOR DE PUESTA A TIERRA
# Basado en el amperaje del interruptor del circuito
# ════════════════════════════════════════════════════════════════════
 
# (amperaje_max, calibre_cobre, calibre_aluminio)
TIERRA_TABLA_250_122 = [
    (15,    "14 AWG",  "12 AWG"),
    (20,    "12 AWG",  "10 AWG"),
    (60,    "10 AWG",  "8 AWG"),
    (100,   "8 AWG",   "6 AWG"),
    (200,   "6 AWG",   "4 AWG"),
    (300,   "4 AWG",   "2 AWG"),
    (400,   "3 AWG",   "1 AWG"),
    (500,   "2 AWG",   "1/0 AWG"),
    (600,   "1 AWG",   "2/0 AWG"),
    (800,   "1/0 AWG", "3/0 AWG"),
    (1000,  "2/0 AWG", "4/0 AWG"),
    (1200,  "3/0 AWG", "250 KCM"),
    (1600,  "4/0 AWG", "350 KCM"),
    (2000,  "250 KCM", "400 KCM"),
    (2500,  "350 KCM", "600 KCM"),
    (3000,  "400 KCM", "600 KCM"),
    (4000,  "500 KCM", "750 KCM"),
    (5000,  "700 KCM", "1200 KCM"),
    (6000,  "800 KCM", "1200 KCM"),
]
 
 
def calibre_tierra_minimo(amperaje_interruptor: float,
                           material: str = "cobre") -> Optional[str]:
    """Devuelve el calibre mínimo de tierra física según el amperaje del ITM."""
    if not amperaje_interruptor or amperaje_interruptor <= 0:
        return None
    col = 1 if material.lower().startswith("cob") else 2
    for amp_max, cu, al in TIERRA_TABLA_250_122:
        if amperaje_interruptor <= amp_max:
            return cu if col == 1 else al
    return None
 
 
# ════════════════════════════════════════════════════════════════════
# CAP. 9 TABLA 9 NEC — RESISTENCIA Y REACTANCIA (Ω/km)
# Para conductores en canalización magnética (acero) a 75°C, FP=0.85
# ════════════════════════════════════════════════════════════════════
 
# calibre: (R_cobre, XL_cobre, R_aluminio, XL_aluminio) en Ω/km
RESISTENCIA_REACTANCIA = {
    "14 AWG":   (10.07, 0.240, 16.4,  0.240),
    "12 AWG":   (6.56,  0.226, 10.5,  0.226),
    "10 AWG":   (3.94,  0.213, 6.56,  0.213),
    "8 AWG":    (2.56,  0.213, 4.10,  0.213),
    "6 AWG":    (1.61,  0.210, 2.62,  0.210),
    "4 AWG":    (1.02,  0.207, 1.61,  0.207),
    "3 AWG":    (0.82,  0.205, 1.31,  0.205),
    "2 AWG":    (0.66,  0.197, 1.02,  0.197),
    "1 AWG":    (0.52,  0.197, 0.82,  0.197),
    "1/0 AWG":  (0.39,  0.180, 0.66,  0.180),
    "2/0 AWG":  (0.33,  0.180, 0.52,  0.180),
    "3/0 AWG":  (0.253, 0.180, 0.43,  0.180),
    "4/0 AWG":  (0.203, 0.180, 0.33,  0.180),
    "250 KCM":  (0.171, 0.171, 0.279, 0.171),
    "300 KCM":  (0.144, 0.167, 0.233, 0.167),
    "350 KCM":  (0.125, 0.164, 0.200, 0.164),
    "400 KCM":  (0.108, 0.161, 0.174, 0.161),
    "500 KCM":  (0.0875, 0.157, 0.141, 0.157),
    "600 KCM":  (0.0741, 0.157, 0.118, 0.157),
    "750 KCM":  (0.0610, 0.157, 0.0951, 0.157),
    "1000 KCM": (0.0464, 0.151, 0.0721, 0.151),
}
 
 
# ════════════════════════════════════════════════════════════════════
# INTERRUPTORES COMERCIALES ESTÁNDAR
# ════════════════════════════════════════════════════════════════════
AMPERAJES_COMERCIALES = [15, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80,
                          90, 100, 110, 125, 150, 175, 200, 225, 250,
                          300, 350, 400, 450, 500, 600, 700, 800, 1000]
 
 
# ════════════════════════════════════════════════════════════════════
# UTILIDADES
# ════════════════════════════════════════════════════════════════════
def _normalizar_calibre(calibre) -> str:
    """Normaliza el calibre para buscar en las tablas."""
    if not calibre:
        return ""
    c = str(calibre).strip().upper()
    c = c.replace("  ", " ")
    if "AWG" not in c and "KCM" not in c and "MCM" not in c:
        c = c + " AWG"
    c = c.replace("MCM", "KCM")
    return c
 
 
def _safe_float(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None
 
 
# ════════════════════════════════════════════════════════════════════
# CÁLCULOS PRINCIPALES
# ════════════════════════════════════════════════════════════════════
def corriente_nominal(carga_w, tension_v, fp=0.9, fases=1) -> Optional[float]:
    """
    Corriente nominal:
      - Mono/Bi: I = P / (V × FP)
      - Trifásico: I = P / (√3 × V × FP)
    """
    w = _safe_float(carga_w)
    v = _safe_float(tension_v)
    f = _safe_float(fp) or 0.9
    try:
        p = int(fases or 1)
    except (ValueError, TypeError):
        p = 1
    if not w or not v or w <= 0 or v <= 0 or f <= 0:
        return None
    if p == 3:
        return w / (SQRT3 * v * f)
    return w / (v * f)
 
 
def corriente_corregida(In, factor_temp=1.0, factor_agrup=1.0) -> Optional[float]:
    """
    Ic = In / (Ft × Fa)
    NOTA: La forma profesional en cuadros de carga es Ic = In × 1.25
    (factor de seguridad del 125% por carga continua, Art. 210-19/220-3),
    luego corregida adicionalmente por temperatura y agrupamiento.
    Aquí aplicamos: Ic = (In × 1.25) / (Ft × Fa)
    """
    if In is None or In <= 0:
        return None
    ft = _safe_float(factor_temp) or 1.0
    fa = _safe_float(factor_agrup) or 1.0
    if ft <= 0 or fa <= 0:
        return None
    return (In * 1.25) / (ft * fa)
 
 
def watts_a_kw(watts) -> float:
    w = _safe_float(watts)
    return (w / 1000.0) if w else 0.0
 
 
def kw_a_kva(kw, fp=0.9) -> float:
    k = _safe_float(kw)
    f = _safe_float(fp) or 0.9
    if not k or k <= 0 or f <= 0:
        return 0.0
    return k / f
 
 
def caida_tension_porcentual(In, longitud_m, calibre, fases, tension_v,
                              material="cobre", fp=0.9) -> Optional[float]:
    """
    Caída de tensión en %, usando R y XL de la tabla 9 NEC.
    Para FP=1.0 (resistivo puro): solo R cuenta.
    Para FP<1.0: %e = (k × I × L × (R·cos(φ) + XL·sen(φ))) / V × 100
      donde k=2 para mono, k=√3 para trifásico.
    """
    i = _safe_float(In)
    l = _safe_float(longitud_m)
    v = _safe_float(tension_v)
    f = _safe_float(fp) or 0.9
    try:
        p = int(fases or 1)
    except (ValueError, TypeError):
        p = 1
 
    if not i or not l or not v or i <= 0 or l <= 0 or v <= 0 or not calibre:
        return None
 
    cal_key = _normalizar_calibre(calibre)
    if cal_key not in RESISTENCIA_REACTANCIA:
        return None
 
    R_cu, XL_cu, R_al, XL_al = RESISTENCIA_REACTANCIA[cal_key]
    if material.lower().startswith("al"):
        R, XL = R_al, XL_al
    else:
        R, XL = R_cu, XL_cu
 
    # Convertir Ω/km a Ω/m
    R_m = R / 1000.0
    XL_m = XL / 1000.0
 
    # Componentes
    cos_phi = f
    sin_phi = sqrt(max(0, 1 - f * f))
    z_efectivo = R_m * cos_phi + XL_m * sin_phi
 
    k = SQRT3 if p == 3 else 2
 
    delta_v = k * i * l * z_efectivo
    return (delta_v / v) * 100.0
 
 
def ampacidad_calibre(calibre, material="cobre", aislamiento_c=75) -> Optional[float]:
    """
    Ampacidad de un calibre según tabla 310-15(B)(16).
    Material: 'cobre' o 'aluminio'
    Aislamiento: 60, 75 o 90 °C
    """
    if not calibre:
        return None
    cal_key = _normalizar_calibre(calibre)
    tabla = AMPACIDAD_COBRE if material.lower().startswith("co") else AMPACIDAD_ALUMINIO
    if cal_key not in tabla:
        return None
    idx = {60: 0, 75: 1, 90: 2}.get(aislamiento_c, 1)
    return tabla[cal_key][idx]
 
 
def interruptor_recomendado(In) -> Optional[int]:
    """Siguiente valor comercial >= In × 1.25"""
    i = _safe_float(In)
    if not i or i <= 0:
        return None
    valor_minimo = i * 1.25
    for amp in AMPERAJES_COMERCIALES:
        if amp >= valor_minimo:
            return amp
    return None
 
 
def calibre_recomendado_por_ampacidad(Ic, material="cobre", aislamiento_c=75) -> Optional[str]:
    """Primer calibre cuya ampacidad >= Ic"""
    if Ic is None or Ic <= 0:
        return None
    tabla = AMPACIDAD_COBRE if material.lower().startswith("co") else AMPACIDAD_ALUMINIO
    idx = {60: 0, 75: 1, 90: 2}.get(aislamiento_c, 1)
    for calibre, ampacidades in tabla.items():
        if ampacidades[idx] >= Ic:
            return calibre
    return None
 
 
# ════════════════════════════════════════════════════════════════════
# EVALUACIÓN NOM POR CIRCUITO
# ════════════════════════════════════════════════════════════════════
def evaluar_circuito_nom(circuito: Dict, calculos: Dict) -> Dict:
    """
    Evalúa contra criterios NOM:
      - ok (verde): todo cumple
      - warn (amarillo): faltan datos para validar
      - fail (rojo): no cumple un criterio crítico
    """
    mensajes = []
    estado = "ok"
 
    Ic = calculos.get("Ic")
    caida = calculos.get("caida_pct")
    calibre = circuito.get("calibre_fase")
    interruptor_a = _safe_float(circuito.get("amperaje_a"))
    In = calculos.get("In")
    material = "cobre"  # default
    aislamiento_c = 75
 
    # Validación 1: ¿Calibre soporta Ic?
    if Ic is not None and calibre:
        amp_max = ampacidad_calibre(calibre, material, aislamiento_c)
        if amp_max is not None:
            if Ic > amp_max:
                estado = "fail"
                mensajes.append(
                    f"Ic={Ic:.1f}A excede ampacidad de {calibre} ({amp_max}A)"
                )
        else:
            if estado == "ok":
                estado = "warn"
            mensajes.append(f"Calibre {calibre} no reconocido en tablas NOM")
    elif not calibre and Ic is not None:
        if estado == "ok":
            estado = "warn"
        mensajes.append("Falta capturar calibre de fase")
 
    # Validación 2: caída de tensión ≤ 3% (derivado)
    if caida is not None:
        if caida > 3.0:
            estado = "fail"
            mensajes.append(f"Caída {caida:.2f}% > 3% (NOM 210-19)")
        elif caida > 2.5 and estado != "fail":
            if estado == "ok":
                estado = "warn"
            mensajes.append(f"Caída {caida:.2f}% cerca del límite")
 
    # Validación 3: Interruptor adecuado
    if In is not None and interruptor_a:
        if interruptor_a < In:
            estado = "fail"
            mensajes.append(
                f"Interruptor de {interruptor_a:.0f}A insuficiente para In={In:.1f}A"
            )
        elif interruptor_a < In * 1.25 and estado != "fail":
            if estado == "ok":
                estado = "warn"
            mensajes.append(
                f"ITM {interruptor_a:.0f}A < 125% de In ({In*1.25:.1f}A)"
            )
 
    if not mensajes:
        mensajes.append("OK")
 
    return {"estado": estado, "mensajes": mensajes}
 
 
# ════════════════════════════════════════════════════════════════════
# CÁLCULO COMPLETO DE UN CIRCUITO
# ════════════════════════════════════════════════════════════════════
def calcular_circuito_completo(circuito: Dict, tension_default=220,
                                temperatura_ambiente=TEMP_AMBIENTE_DEFAULT_C,
                                material=None,
                                aislamiento_c=None) -> Dict:
    """
    Aplica todos los cálculos a un circuito y devuelve el bloque enriquecido.
 
    - El material del conductor se lee del campo `material` del circuito.
      Si no viene, se usa el parámetro `material` (default 'cobre').
    - El aislamiento se decide AUTOMÁTICAMENTE según el amperaje del ITM:
        ITM ≤ 100A → columna 60°C
        ITM > 100A → columna 75°C
      (NEC 110.14(C) / NOM-001). Si se pasa el parámetro `aislamiento_c`
      ese valor se respeta y se ignora la regla automática.
    """
    polos = int(circuito.get("polos") or 1)
    carga_w = circuito.get("carga_w") or 0
    fp = _safe_float(circuito.get("factor_potencia")) or 0.9
    tension_v = _safe_float(circuito.get("tension_v")) or tension_default
    longitud = circuito.get("longitud_m")
    calibre = circuito.get("calibre_fase")
    amperaje_itm = _safe_float(circuito.get("amperaje_a"))
 
    # Material: del circuito o default
    if material is None:
        material = (circuito.get("material") or "cobre").lower()
 
    # Aislamiento: regla automática 60/75 según ITM (NEC 110.14(C))
    if aislamiento_c is None:
        aislamiento_c = aislamiento_segun_itm(amperaje_itm)
 
    # Cálculos básicos
    kw = watts_a_kw(carga_w)
    kva = kw_a_kva(kw, fp)
    In = corriente_nominal(carga_w, tension_v, fp, polos)
 
    # Factores de corrección
    ft = factor_correccion_temperatura(temperatura_ambiente, aislamiento_c)
    fa = factor_correccion_agrupamiento(conductores_activos_circuito(polos))
 
    Ic = corriente_corregida(In, ft, fa)
 
    # Caída de tensión
    caida = caida_tension_porcentual(In, longitud, calibre, polos, tension_v,
                                       material, fp) if In else None
 
    # Reactancia y resistencia para mostrar
    XL, R = None, None
    if calibre:
        cal_key = _normalizar_calibre(calibre)
        if cal_key in RESISTENCIA_REACTANCIA:
            if material.lower().startswith("al"):
                R, XL = RESISTENCIA_REACTANCIA[cal_key][2], RESISTENCIA_REACTANCIA[cal_key][3]
            else:
                R, XL = RESISTENCIA_REACTANCIA[cal_key][0], RESISTENCIA_REACTANCIA[cal_key][1]
 
    # Calibre mínimo de tierra
    cal_tierra = calibre_tierra_minimo(amperaje_itm, material) if amperaje_itm else None
 
    # Conductores activos
    cond_activos = conductores_activos_circuito(polos)
 
    res = {
        "watts":            float(carga_w) if carga_w else 0.0,
        "kw":               kw,
        "kva":              kva,
        "tension_v":        float(tension_v) if tension_v else 0.0,
        "fp":               float(fp),
        "polos":            polos,
        "In":               In,
        "Ic":               Ic,
        "caida_pct":        caida,
        "factor_temp":      ft,
        "factor_agrup":     fa,
        "resistencia":      R,
        "reactancia":       XL,
        "calibre_tierra_min": cal_tierra,
        "cond_activos":     cond_activos,
        "material":         material,
        "aislamiento_c":    aislamiento_c,
    }
    res["evaluacion"] = evaluar_circuito_nom(circuito, res)
    return res
 
 
# ════════════════════════════════════════════════════════════════════
# BALANCE DE FASES
# ════════════════════════════════════════════════════════════════════
def asignar_fase_secuencial(espacio_inicio: int, polos: int) -> str:
    """
    Convención secuencial de asignación de fases:
      Lado izquierdo (impar): 1=A, 3=B, 5=C, 7=A...
      Lado derecho (par):     2=A, 4=B, 6=C, 8=A...
    Bifásico: ocupa 2 fases (A-B, B-C, C-A)
    Trifásico: A-B-C
    """
    if not espacio_inicio or espacio_inicio < 1:
        return ""
    fases_orden = ["A", "B", "C"]
    if espacio_inicio % 2 == 1:
        idx_orden = (espacio_inicio - 1) // 2
    else:
        idx_orden = (espacio_inicio - 2) // 2
    fase_inicial = fases_orden[idx_orden % 3]
 
    if polos == 1:
        return fase_inicial
    elif polos == 2:
        idx = fases_orden.index(fase_inicial)
        f2 = fases_orden[(idx + 1) % 3]
        return f"{fase_inicial}-{f2}"
    elif polos == 3:
        return "A-B-C"
    return fase_inicial
 
 
def calcular_balance_fases(circuitos_con_calculo: List[Dict]) -> Dict:
    """Suma watts por fase. Para multi-fase, reparte equitativamente."""
    suma = {"A": 0.0, "B": 0.0, "C": 0.0}
    for c in circuitos_con_calculo:
        fase = c.get("fase_asignada", "")
        watts = _safe_float(c.get("watts")) or 0
        if watts <= 0 or not fase:
            continue
        fases = fase.split("-")
        watts_por_fase = watts / len(fases)
        for f in fases:
            f = f.strip().upper()
            if f in suma:
                suma[f] += watts_por_fase
    return suma
 
 
# ════════════════════════════════════════════════════════════════════
# CÁLCULO DEL ALIMENTADOR PRINCIPAL
# ════════════════════════════════════════════════════════════════════
def calcular_alimentador_principal(circuitos_calculados: List[Dict],
                                     tension_v: float = 220,
                                     fp_promedio: float = 0.9,
                                     temperatura_ambiente=TEMP_AMBIENTE_DEFAULT_C,
                                     aislamiento_c=75) -> Dict:
    """Suma los watts de todos los circuitos para el alimentador principal."""
    suma_w = sum((c.get("watts") or 0) for c in circuitos_calculados)
    kw = suma_w / 1000.0
    kva = kw / fp_promedio if fp_promedio > 0 else 0
    if tension_v > 0 and fp_promedio > 0 and suma_w > 0:
        In_total = suma_w / (SQRT3 * tension_v * fp_promedio)
    else:
        In_total = 0
 
    ft = factor_correccion_temperatura(temperatura_ambiente, aislamiento_c)
    Ic_total = (In_total * 1.25) / ft if In_total else 0
 
    return {
        "watts":         suma_w,
        "kw":            kw,
        "kva":           kva,
        "tension_v":     tension_v,
        "fp":            fp_promedio,
        "In":            In_total,
        "Ic":            Ic_total,
        "factor_temp":   ft,
    }