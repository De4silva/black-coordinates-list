import httpx
from fastapi import APIRouter, HTTPException

from app.schemas import IPRequest
from app.services import IPGeolocationService


router = APIRouter()

geolocation_service = IPGeolocationService()


@router.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "service-a",
    }


@router.post("/resolve-ip")
def resolve_ip(request: IPRequest):
    try:
        location_data = geolocation_service.resolve_ip(str(request.ip))
        return location_data

    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail="External IP geolocation service returned an error",
        ) from exc

    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=503,
            detail="External IP geolocation service is unavailable",
        ) from exc