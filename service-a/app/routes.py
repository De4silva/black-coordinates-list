import httpx
from fastapi import APIRouter, HTTPException

from app.schemas import IPRequest, IPListRequest
from app.services import IPGeolocationService, CoordinateServiceClient


router = APIRouter()

geolocation_service = IPGeolocationService()
coordinate_service = CoordinateServiceClient()


@router.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "service-a",
    }
def resolve_and_save(ip_address: str):
    location = geolocation_service.resolve_ip(ip_address)

    coordinate = {
        "ip": location["ip"],
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "country": location["country"],
        "city": location["city"],
    }

    saved = coordinate_service.create_coordinate(coordinate)

    return {
        "location": location,
        "saved_coordinate": saved,
    }

@router.post("/resolve-ip")
def resolve_ip(request: IPRequest):
    try:
        return resolve_and_save(str(request.ip))

    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail="Upstream service returned an error",
        ) from exc

    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=503,
            detail="Upstream service is unavailable",
        ) from exc

@router.post("/resolve-ip-list")
def resolve_ip_list(request: IPListRequest):
    try:
        return [
            resolve_and_save(str(ip_address))
            for ip_address in request.ips
        ]

    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail="Upstream service returned an error",
        ) from exc

    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=503,
            detail="Upstream service is unavailable",
        ) from exc