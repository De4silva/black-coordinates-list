from pydantic import BaseModel, IPvAnyAddress


class IPRequest(BaseModel):
    ip: IPvAnyAddress


class IPListRequest(BaseModel):
    ips: list[IPvAnyAddress]