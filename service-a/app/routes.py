import httpx
from fastapi import APIRouter, HTTPException

from app.schemas import IPRequest
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


@router.post("/resolve-ip")
def resolve_ip(request: IPRequest):
    try:
        location_data = geolocation_service.resolve_ip(str(request.ip))

        coordinate_data = {
            "ip": location_data["ip"],
            "latitude": location_data["latitude"],
            "longitude": location_data["longitude"],
            "country": location_data["country"],
            "city": location_data["city"],
        }

        saved_coordinate = coordinate_service.create_coordinate(coordinate_data)

        return {
            "location": location_data,
            "saved_coordinate": saved_coordinate,
        }

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