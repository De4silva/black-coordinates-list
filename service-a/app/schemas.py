from pydantic import BaseModel, IPvAnyAddress


class IPRequest(BaseModel):
    ip: IPvAnyAddress