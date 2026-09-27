# ui_state.py
"""
Módulo para persistir estado de la interfaz entre sesiones.
Guarda un JSON en AppData\\Local\\CAMF\\ui_state.json (misma carpeta de memoria.db).

Uso:
    from ui_state import cargar_estado, guardar_estado

    # cargar (devuelve {} si no existe)
    estado = cargar_estado()
    contraidos = estado.get("grupos_contraidos_tableros", [])

    # guardar
    estado["grupos_contraidos_tableros"] = [1, 3, 5]
    guardar_estado(estado)

El archivo es pequeño (solo IDs y flags de UI). Si se corrompe o se borra,
simplemente se recrea vacío sin afectar la BD ni los datos del usuario.
"""

import os
import json
from typing import Dict, Any

UI_STATE_FILE = "ui_state.json"


def _get_state_path() -> str:
    """Misma carpeta que memoria.db: AppData\\Local\\CAMF\\ (Windows)."""
    base_dir = os.path.join(os.getenv('LOCALAPPDATA', os.getcwd()), "CAMF")
    os.makedirs(base_dir, exist_ok=True)
    return os.path.join(base_dir, UI_STATE_FILE)


def cargar_estado() -> Dict[str, Any]:
    """
    Lee el archivo de estado y devuelve un diccionario.
    Si el archivo no existe o está corrupto, devuelve {} sin lanzar excepción.
    """
    path = _get_state_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return {}
            return data
    except Exception as e:
        print(f"[UI_STATE] No se pudo leer {path}: {e}")
        return {}


def guardar_estado(estado: Dict[str, Any]) -> bool:
    """
    Guarda el diccionario completo como JSON. Devuelve True si tuvo éxito.
    """
    path = _get_state_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(estado, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[UI_STATE] No se pudo guardar {path}: {e}")
        return False


# ── Helpers especializados para grupos contraídos ────────────────────────────
# Hacemos funciones de conveniencia para no repetir la clave en cada llamada.

def _clave_contraidos(tabla_db: str) -> str:
    """Clave en el JSON para los grupos contraídos de cada pestaña."""
    return f"grupos_contraidos_{tabla_db}"


def obtener_grupos_contraidos(tabla_db: str) -> set:
    """
    Devuelve un set con los IDs de grupos que estaban contraídos
    en la última sesión, para una pestaña específica (tableros/transformadores).
    """
    estado = cargar_estado()
    lista = estado.get(_clave_contraidos(tabla_db), [])
    return set(lista) if isinstance(lista, list) else set()


def guardar_grupos_contraidos(tabla_db: str, ids_contraidos: set):
    """Guarda el set de IDs de grupos contraídos para una pestaña."""
    estado = cargar_estado()
    estado[_clave_contraidos(tabla_db)] = sorted(list(ids_contraidos))
    guardar_estado(estado)


# ── Helpers genéricos clave/valor ───────────────────────────────────────────
# Para no tener que crear una función especializada por cada cosa nueva que
# se quiera persistir (anchos de columnas, posiciones de ventana, etc).
 
def obtener_valor(clave: str, default: Any = None) -> Any:
    """Devuelve el valor asociado a la clave o el default si no existe."""
    estado = cargar_estado()
    return estado.get(clave, default)
 
 
def guardar_valor(clave: str, valor: Any) -> bool:
    """Guarda un valor bajo la clave especificada. No toca el resto del estado."""
    estado = cargar_estado()
    estado[clave] = valor
    return guardar_estado(estado)