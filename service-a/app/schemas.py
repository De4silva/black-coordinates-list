from pydantic import BaseModel, EmailStr, IPvAnyAddress


class IPRequest(BaseModel):
    ip: IPvAnyAddress


class IPListRequest(BaseModel):
    ips: list[IPvAnyAddress]


class SigninRequest(BaseModel):
    email: EmailStr
    password: str | None = None
    ip: IPvAnyAddress
