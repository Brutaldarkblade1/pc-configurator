from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator


class RegisterIn(BaseModel):
    email: EmailStr
    username: str | None = Field(default=None, max_length=20)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def password_strength(cls, value: str) -> str:
        has_digit = any(ch.isdigit() for ch in value)
        if not has_digit:
            raise ValueError("Heslo musí obsahovat alespoň 1 číslo.")
        has_upper = any(ch.isupper() for ch in value)
        if not has_upper:
            raise ValueError("Heslo musí obsahovat alespoň 1 velké písmeno.")
        return value


class RegisterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    username: str | None
    is_verified: bool


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ResendVerificationIn(BaseModel):
    email: EmailStr
