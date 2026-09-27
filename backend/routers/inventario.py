from fastapi import APIRouter, Depends, HTTPException
from typing import List, Dict, Any

from db.db_manager import insertar_datos, obtener_datos
from main import get_current_active_user
from auth import require_role

router = APIRouter(prefix="/inventario", tags=["Inventario"])


# ===============================
# TABLEROS
# ===============================

@router.get("/tableros")
def obtener_tableros(current_user = Depends(get_current_active_user)):
    """
    Devuelve todos los tableros registrados.
    """
    tableros = obtener_datos("tableros")
    return {"tableros": tableros}


@router.post("/tableros")
def crear_tablero(
    data: Dict[str, Any],
    user = Depends(require_role(["admin", "supervisor"]))
):
    """
    Crear un nuevo tablero.
    """
    tablero_id = insertar_datos("tableros", data)

    return {
        "message": "Tablero creado",
        "id": tablero_id
    }


# ===============================
# TRANSFORMADORES
# ===============================

@router.get("/transformadores")
def obtener_transformadores(current_user = Depends(get_current_active_user)):
    """
    Devuelve todos los transformadores.
    """
    transformadores = obtener_datos("transformadores")
    return {"transformadores": transformadores}


@router.post("/transformadores")
def crear_transformador(
    data: Dict[str, Any],
    user = Depends(require_role(["admin", "supervisor"]))
):
    """
    Crear transformador.
    """

    transformador_id = insertar_datos("transformadores", data)

    return {
        "message": "Transformador creado",
        "id": transformador_id
    }