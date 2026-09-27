from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import engine, Base, SessionLocal
import models, schemas
import auth
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from typing import List

app = FastAPI(title="CAMF API", version="1.0.0")

# Crear tablas
Base.metadata.create_all(bind=engine)

# ---------------- DB ----------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---------------- Seguridad ----------------
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    email = auth.decode_access_token(token)
    if email is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario no encontrado")
    return user

def get_current_active_user(current_user: models.User = Depends(get_current_user)):
    if not current_user.activo:
        raise HTTPException(status_code=400, detail="Usuario inactivo")
    return current_user

def require_role(allowed_roles: List[str]):
    def role_checker(current_user: models.User = Depends(get_current_active_user)):
        if current_user.rol not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para realizar esta acción"
            )
        return current_user
    return role_checker

# ---------------- Endpoints ----------------
@app.get("/")
def root():
    return {"message": "CAMF Backend Running"}

# Registro de usuario
@app.post("/users/", response_model=schemas.UserResponse)
def create_user(user: schemas.UserCreate, db: Session = Depends(get_db)):

    existing_user = db.query(models.User).filter(models.User.email == user.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="El email ya está registrado")

    hashed_pwd = auth.hash_password(user.password)
    new_user = models.User(
        nombre=user.nombre,
        email=user.email,
        hashed_password=hashed_pwd,
        rol=user.rol
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

# Login
@app.post("/login", response_model=schemas.Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    if not user or not auth.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Email o contraseña incorrectos")
    access_token = auth.create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}

# Endpoint protegido
@app.get("/protected")
def protected_route(current_user: models.User = Depends(get_current_active_user)):
    return {"message": f"Hola {current_user.nombre}, tu rol es {current_user.rol}"}

# Endpoint admin
@app.get("/admin-only")
def admin_only(user = Depends(require_role(["admin"]))):
    return {
        "message": f"Bienvenido admin {user.nombre}"
    }