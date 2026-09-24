import httpx
from fastapi import FastAPI, HTTPException

app = FastAPI(title="Service C")

FREE_IP_API_URL = "https://free.freeipapi.com/api/v1/json"


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "service-c"}


@app.get("/resolve-ip/{ip_address}")
def resolve_ip(ip_address: str):
    try:
        response = httpx.get(
            f"{FREE_IP_API_URL}/{ip_address}",
            timeout=10.0,
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

    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail="Free IP API returned an error",
        ) from exc

    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=503,
            detail="Free IP API is unavailable",
        ) from exc