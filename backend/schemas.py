from pydantic import BaseModel, EmailStr

class UserBase(BaseModel):
    nombre: str
    email: EmailStr
    rol: str = "tecnico"

class UserCreate(UserBase):
    password: str

class UserResponse(UserBase):
    id: int
    activo: bool

    class Config:
        orm_mode = True

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: str | None = None