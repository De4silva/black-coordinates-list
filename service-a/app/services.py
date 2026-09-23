import httpx


class IPGeolocationService:
    BASE_URL = "https://free.freeipapi.com/api/v1/json"

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout

    def resolve_ip(self, ip_address: str) -> dict:
        url = f"{self.BASE_URL}/{ip_address}"

        response = httpx.get(
            url,
            timeout=self.timeout,
        )

        response.raise_for_status()

        data = response.json()

        return {
            "ip": data.get("ipAddress", ip_address),
            "latitude": data.get("latitude"),
            "longitude": data.get("longitude"),
            "country": data.get("countryName"),
            "city": data.get("cityName"),
            "isp": data.get("asnOrganization"),
        }