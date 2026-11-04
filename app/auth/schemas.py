from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator

from app.config import get_settings

OrgName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class OrgOut(BaseModel):
    id: UUID
    name: str


class RegisterRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=False)

    org_name: OrgName
    email: EmailStr
    password: str = Field(min_length=1)

    @field_validator("email")
    @classmethod
    def _lower_email(cls, v: str) -> str:
        return v.lower()

    @field_validator("password")
    @classmethod
    def _password_length(cls, v: str) -> str:
        s = get_settings()
        if len(v) < s.password_min_length:
            raise ValueError(f"Password must be at least {s.password_min_length} characters")
        if len(v) > s.password_max_length:
            raise ValueError(f"Password must be at most {s.password_max_length} characters")
        return v


class RegisterResponse(BaseModel):
    token: str = Field(description="Admin JWT for the dashboard")
    org: OrgOut


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def _lower_email(cls, v: str) -> str:
        return v.lower()


class LoginResponse(BaseModel):
    token: str = Field(description="Admin JWT for the dashboard")


class MeResponse(BaseModel):
    org: OrgOut
    email: str
