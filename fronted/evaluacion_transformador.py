# evaluacion_transformador.py
"""
Motor de veredicto normativo para pruebas de mantenimiento a transformadores.

Este módulo es AUTOCONTENIDO: no depende de UI ni de BD. Toma un código de
prueba y un valor capturado, y devuelve un veredicto (aprobada / atención /
falla) junto con la norma que respalda el veredicto y una recomendación
textual cuando aplica.

Uso previsto:
    - Durante la CAPTURA (dentro de DialogCerrarMantenimiento), NO se llama
      este módulo: la captura es rápida, sin evaluación en vivo.
    - En la VISTA FINALIZADA (dentro de _bloque_cierre de ficha_mantenimiento),
      se llama para cada prueba capturada y se pinta el chip de veredicto
      junto al valor, con la cita de norma como tooltip y la recomendación
      como texto complementario cuando el veredicto es atención o falla.

Fuentes normativas:
    - IEEE Std 43-2018: Recommended Practice for Testing Insulation
      Resistance of Electric Machinery.
    - IEEE C57.152-2013: Guide for Diagnostic Field Testing of Fluid-Filled
      Power Transformers, Regulators, and Reactors.
    - IEEE C57.106-2015: Guide for Acceptance and Maintenance of Insulating
      Mineral Oil in Electrical Equipment.
    - IEEE C57.12.90-2015: Standard Test Code for Liquid-Immersed
      Distribution, Power, and Regulating Transformers.

Los umbrales de este módulo reflejan práctica de mantenimiento industrial
en México para transformadores de distribución (clase ≤ 69 kV). Para
transformadores de potencia (> 10 MVA, clase > 69 kV) se requieren
umbrales adicionales que quedan fuera del MVP.
"""

from typing import Optional


# ─── Catálogo de códigos de prueba ────────────────────────────────────────
# Cada prueba tiene un código estable (usado como clave en BD, para que
# los umbrales puedan ajustarse sin romper datos históricos). El código NO
# debe cambiar una vez que hay registros usándolo.

# Pruebas eléctricas comunes (aplican a aceite y aire)
PRUEBA_RES_AISL_AT_TIERRA   = "res_aisl_at_tierra"
PRUEBA_RES_AISL_BT_TIERRA   = "res_aisl_bt_tierra"
PRUEBA_RES_AISL_AT_BT       = "res_aisl_at_bt"
PRUEBA_INDICE_POLARIZACION  = "indice_polarizacion"
PRUEBA_TTR_ERROR            = "ttr_error_pct"
PRUEBA_RES_DEVANADOS_DESV   = "res_devanados_desv_pct"
PRUEBA_TERMOGRAFIA          = "termografia_rise_c"

# Pruebas al aceite (solo transformadores con enfriamiento = "Aceite")
PRUEBA_RIGIDEZ_ACEITE       = "rigidez_aceite_kv"
PRUEBA_HUMEDAD_ACEITE       = "humedad_aceite_ppm"
PRUEBA_ACIDEZ_ACEITE        = "acidez_aceite_koh"


# ─── Códigos de veredicto ─────────────────────────────────────────────────
VEREDICTO_APROBADA = "aprobada"
VEREDICTO_ATENCION = "atencion"
VEREDICTO_FALLA    = "falla"


# ─── Metadata de cada prueba ──────────────────────────────────────────────
# El dict interno "reglas" define umbrales. La convención de comparación:
#   - Si "aprobada_min" está definido: valor ≥ aprobada_min → aprobada
#   - Si "aprobada_max" está definido: valor ≤ aprobada_max → aprobada
#   - Si "falla_min" está definido: valor < falla_min → falla
#   - Si "falla_max" está definido: valor > falla_max → falla
#   - El rango intermedio es "atención"
#
# La "norma" es la cita bibliográfica que sustenta los umbrales; se muestra
# como tooltip / información complementaria en la vista finalizada.
# Las recomendaciones son textuales, mostradas junto al veredicto cuando
# es "atencion" o "falla".

_CATALOGO = {
    PRUEBA_RES_AISL_AT_TIERRA: {
        "nombre": "Resistencia de aislamiento AT → tierra (Megger)",
        "unidad": "MΩ",
        "aplica_a": ("aire", "aceite"),
        "reglas": {
            "aprobada_min": 100.0,   # ≥ 100 MΩ (sistemas buenos)
            "falla_min":    10.0,    # < 10 MΩ (falla)
        },
        "norma": (
            "IEEE Std 43-2018 · piso mínimo = kV_nominal + 1 MΩ. "
            "Sistemas buenos ≥ 100 MΩ; ideal ≥ 1000 MΩ. "
            "Todas las mediciones normalizadas a 20 °C."
        ),
        "recomendacion_atencion": (
            "Programar seguimiento en próximo mantenimiento. "
            "Considerar secado si la tendencia decrece."
        ),
    },
    PRUEBA_RES_AISL_BT_TIERRA: {
        "nombre": "Resistencia de aislamiento BT → tierra (Megger)",
        "unidad": "MΩ",
        "aplica_a": ("aire", "aceite"),
        "reglas": {
            "aprobada_min": 100.0,
            "falla_min":    10.0,
        },
        "norma": (
            "IEEE Std 43-2018 · piso mínimo = kV_nominal + 1 MΩ. "
            "Sistemas buenos ≥ 100 MΩ."
        ),
        "recomendacion_atencion": (
            "Programar seguimiento en próximo mantenimiento. "
            "Considerar secado si la tendencia decrece."
        ),
    },
    PRUEBA_RES_AISL_AT_BT: {
        "nombre": "Resistencia de aislamiento AT ↔ BT (Megger)",
        "unidad": "MΩ",
        "aplica_a": ("aire", "aceite"),
        "reglas": {
            "aprobada_min": 100.0,
            "falla_min":    10.0,
        },
        "norma": (
            "IEEE Std 43-2018 · piso mínimo = kV_nominal + 1 MΩ. "
            "Sistemas buenos ≥ 100 MΩ."
        ),
        "recomendacion_atencion": (
            "Programar seguimiento en próximo mantenimiento. "
            "Considerar secado si la tendencia decrece."
        ),
    },
    PRUEBA_INDICE_POLARIZACION: {
        "nombre": "Índice de polarización (IP = R@10min / R@1min)",
        "unidad": "",  # adimensional (ratio)
        "aplica_a": ("aire", "aceite"),
        "reglas": {
            "aprobada_min": 1.5,
            "falla_min":    1.0,
        },
        "norma": (
            "IEEE C57.152-2013, cláusula 7.2.13.4. En transformadores en "
            "aceite el IP es típicamente menor al de motores por el aceite "
            "cuyo índice se acerca a 1.0. IP de 1.5 es aceptable."
        ),
        "recomendacion_atencion": (
            "Aislamiento con síntomas de humedad. "
            "Considerar prueba de factor de potencia (Doble)."
        ),
    },
    PRUEBA_TTR_ERROR: {
        "nombre": "Relación de transformación (TTR) · error %",
        "unidad": "%",
        "aplica_a": ("aire", "aceite"),
        "reglas": {
            "aprobada_max": 0.5,     # ≤ 0.5% error
            "falla_max":    1.0,     # > 1.0% error → falla
        },
        "norma": "IEEE C57.12.90 · error máximo 0.5% respecto a placa.",
        "recomendacion_atencion": (
            "Verificar taps y cambiador. "
            "Repetir prueba si el error persiste."
        ),
    },
    PRUEBA_RES_DEVANADOS_DESV: {
        "nombre": "Resistencia de devanados · desviación entre fases",
        "unidad": "%",
        "aplica_a": ("aire", "aceite"),
        "reglas": {
            "aprobada_max": 5.0,     # < 5% desviación
            "falla_max":    10.0,    # > 10% desviación → falla
        },
        "norma": (
            "IEEE C57.152-2013 · desbalance de fase típicamente dentro "
            "de 5–10%. Incremento súbito en una fase es advertencia "
            "temprana de falla."
        ),
        "recomendacion_atencion": (
            "Revisar conexiones internas. "
            "Termografiar bajo carga."
        ),
    },
    PRUEBA_TERMOGRAFIA: {
        "nombre": "Termografía · rise máximo sobre ambiente",
        "unidad": "°C",
        "aplica_a": ("aire", "aceite"),
        "reglas": {
            "aprobada_max": 55.0,
            "falla_max":    65.0,
        },
        "norma": "IEEE C57.152-2013 · rise máximo 65 °C sobre ambiente.",
        "recomendacion_atencion": (
            "Investigar puntos calientes específicos. "
            "Revisar carga y conexiones."
        ),
    },
    # ─── Pruebas al aceite ────────────────────────────────────────────────
    PRUEBA_RIGIDEZ_ACEITE: {
        "nombre": "Rigidez dieléctrica del aceite (ASTM D1816 gap 1 mm)",
        "unidad": "kV",
        "aplica_a": ("aceite",),
        "reglas": {
            "aprobada_min": 30.0,
            "falla_min":    25.0,
        },
        "norma": (
            "IEEE C57.106-2015, Tabla 5. Transformadores clase ≤ 69 kV "
            "en servicio: mínimo 25 kV (falla), 25–30 kV atención, "
            "≥ 30 kV aprobada."
        ),
        "recomendacion_atencion": (
            "Programar filtrado del aceite en los próximos 60 días."
        ),
    },
    PRUEBA_HUMEDAD_ACEITE: {
        "nombre": "Contenido de humedad en aceite (Karl Fischer)",
        "unidad": "ppm",
        "aplica_a": ("aceite",),
        "reglas": {
            "aprobada_max": 20.0,
            "falla_max":    35.0,
        },
        "norma": (
            "IEEE C57.106-2015, Tabla 5. Transformadores clase ≤ 69 kV: "
            "máximo 35 ppm en servicio; < 10 ppm deseable en nuevo."
        ),
        "recomendacion_atencion": (
            "Considerar secado o cambio parcial del aceite."
        ),
    },
    PRUEBA_ACIDEZ_ACEITE: {
        "nombre": "Acidez del aceite (número de neutralización)",
        "unidad": "mg KOH/g",
        "aplica_a": ("aceite",),
        "reglas": {
            "aprobada_max": 0.15,
            "falla_max":    0.30,
        },
        "norma": (
            "IEEE C57.106-2015. Máximo 0.30 mg KOH/g para clase ≤ 69 kV."
        ),
        "recomendacion_atencion": (
            "Aceite envejeciendo. Programar reclamado o reemplazo en "
            "el próximo ciclo mayor."
        ),
    },
}


# ─── API pública ──────────────────────────────────────────────────────────
def evaluar_prueba(codigo: str, valor: Optional[float],
                   contexto: Optional[dict] = None) -> dict:
    """
    Evalúa una prueba capturada contra su norma y devuelve el veredicto.

    Args:
        codigo: código estable de la prueba (constantes PRUEBA_*).
        valor:  valor numérico capturado. Si es None, se devuelve
                veredicto "no_ejecutada".
        contexto: dict opcional con información adicional. Hoy no se usa,
                pero se reserva para futuros umbrales dinámicos
                (ej. resistencia de aislamiento por kV nominal).

    Returns:
        dict con:
            veredicto:       "aprobada" | "atencion" | "falla" | "no_ejecutada"
            valor:           el valor recibido (para trazabilidad)
            nombre:          nombre humano de la prueba
            unidad:          unidad de medida
            norma:           cita bibliográfica que sustenta el veredicto
            recomendacion:   texto sugerido para el reporte (None si aprobada)
            error:           mensaje de error si codigo desconocido, None si OK

    Nunca lanza excepción — todos los casos degradados devuelven un dict
    con "error" no nulo para que el consumidor no tenga que hacer try/except.
    """
    meta = _CATALOGO.get(codigo)
    if meta is None:
        return {
            "veredicto":     "no_ejecutada",
            "valor":         valor,
            "nombre":        codigo,
            "unidad":        "",
            "norma":         "",
            "recomendacion": None,
            "error":         f"Código de prueba desconocido: {codigo!r}",
        }

    if valor is None:
        return {
            "veredicto":     "no_ejecutada",
            "valor":         None,
            "nombre":        meta["nombre"],
            "unidad":        meta["unidad"],
            "norma":         meta["norma"],
            "recomendacion": None,
            "error":         None,
        }

    try:
        v = float(valor)
    except (TypeError, ValueError):
        return {
            "veredicto":     "no_ejecutada",
            "valor":         valor,
            "nombre":        meta["nombre"],
            "unidad":        meta["unidad"],
            "norma":         meta["norma"],
            "recomendacion": None,
            "error":         f"Valor no numérico: {valor!r}",
        }

    veredicto = _decidir_veredicto(v, meta["reglas"])
    recomendacion = _resolver_recomendacion(veredicto, meta)

    return {
        "veredicto":     veredicto,
        "valor":         v,
        "nombre":        meta["nombre"],
        "unidad":        meta["unidad"],
        "norma":         meta["norma"],
        "recomendacion": recomendacion,
        "error":         None,
    }


def pruebas_aplicables(enfriamiento: str) -> list:
    """
    Devuelve la lista de códigos de pruebas que aplican según el tipo de
    enfriamiento del transformador ("Aceite" o "Aire"). El widget de captura
    consume esta función para decidir qué filas mostrar.
    """
    tipo = (enfriamiento or "").strip().lower()
    if tipo not in ("aceite", "aire"):
        # Fallback conservador: mostrar solo las comunes.
        tipo = "aire"

    return [
        codigo for codigo, meta in _CATALOGO.items()
        if tipo in meta["aplica_a"]
    ]


def obtener_metadata(codigo: str) -> Optional[dict]:
    """
    Devuelve la metadata de una prueba (nombre, unidad, norma...) sin
    evaluarla. Útil para pintar encabezados en la vista de captura.
    """
    meta = _CATALOGO.get(codigo)
    if meta is None:
        return None
    return {
        "codigo":  codigo,
        "nombre":  meta["nombre"],
        "unidad":  meta["unidad"],
        "norma":   meta["norma"],
        "aplica_a": tuple(meta["aplica_a"]),
    }


# ─── Helpers internos ─────────────────────────────────────────────────────
def _decidir_veredicto(valor: float, reglas: dict) -> str:
    """
    Aplica las reglas del catálogo al valor numérico y devuelve uno de
    "aprobada" / "atencion" / "falla".

    Convención de reglas:
        - Si "aprobada_min" está: valor ≥ aprobada_min → aprobada
        - Si "aprobada_max" está: valor ≤ aprobada_max → aprobada
        - Si "falla_min" está: valor < falla_min → falla
        - Si "falla_max" está: valor > falla_max → falla
        - Fuera de esos rangos, veredicto es "atencion".

    Una prueba usa MIN o MAX según su dirección de bondad:
        - Aislamiento: más es mejor (usar _min).
        - Humedad, error TTR: menos es mejor (usar _max).
    """
    if "aprobada_min" in reglas:
        # Dirección: más es mejor
        if valor >= reglas["aprobada_min"]:
            return VEREDICTO_APROBADA
        if "falla_min" in reglas and valor < reglas["falla_min"]:
            return VEREDICTO_FALLA
        return VEREDICTO_ATENCION

    if "aprobada_max" in reglas:
        # Dirección: menos es mejor
        if valor <= reglas["aprobada_max"]:
            return VEREDICTO_APROBADA
        if "falla_max" in reglas and valor > reglas["falla_max"]:
            return VEREDICTO_FALLA
        return VEREDICTO_ATENCION

    # Regla sin dirección — degradar a atención
    return VEREDICTO_ATENCION


def _resolver_recomendacion(veredicto: str, meta: dict) -> Optional[str]:
    """
    Devuelve el texto de recomendación según el veredicto. Aprobada = None
    (nada que recomendar). Falla usa un texto genérico si no hay uno
    específico. Atención usa el texto embebido en el catálogo.
    """
    if veredicto == VEREDICTO_APROBADA:
        return None
    if veredicto == VEREDICTO_ATENCION:
        return meta.get("recomendacion_atencion")
    if veredicto == VEREDICTO_FALLA:
        return meta.get(
            "recomendacion_falla",
            "Fuera de norma. Requiere acción correctiva antes de "
            "continuar operación."
        )
    return None
