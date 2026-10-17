import httpx
from fastapi import APIRouter, HTTPException

from app.schemas import IPRequest, IPListRequest, SigninRequest
from app.user_gateway import DuplicateIP, user_gateway
from kafka.errors import KafkaError
from app.services import IPGeolocationService, CoordinateServiceClient


router = APIRouter()

geolocation_service = IPGeolocationService()
coordinate_service = CoordinateServiceClient()


@router.post('/signin', status_code=202)
def signin(request: SigninRequest):
    try:
        user_gateway.publish(str(request.email), str(request.ip))
    except DuplicateIP as exc:
        raise HTTPException(status_code=429, detail='IP already submitted within 60 seconds') from exc
    except KafkaError as exc:
        raise HTTPException(status_code=503, detail='Kafka is unavailable') from exc
    return {'message': 'your request was received'}


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
