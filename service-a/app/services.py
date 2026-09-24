import os
import httpx


class IPGeolocationService:
    BASE_URL = os.getenv("SERVICE_C_URL", "http://127.0.0.1:8001")

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout

    def resolve_ip(self, ip_address: str) -> dict:
        response = httpx.get(
            f"{self.BASE_URL}/resolve-ip/{ip_address}",
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()


class CoordinateServiceClient:
    BASE_URL = os.getenv("SERVICE_B_URL", "http://127.0.0.1:5000")

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout

    def create_coordinate(self, coordinate_data: dict) -> dict:
        url = f"{self.BASE_URL}/api/coordinates"

        response = httpx.post(
            url,
            json=coordinate_data,
            timeout=self.timeout,
        )

        response.raise_for_status()

        return response.json()