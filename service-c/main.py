import logging
import math
import time
from collections import deque
from ipaddress import ip_address as parse_ip
from threading import Lock

import httpx
from fastapi import FastAPI, HTTPException

app = FastAPI(title="Service C")
logger = logging.getLogger("uvicorn.error")
FREE_IP_API_URL = "https://free.freeipapi.com/api/v1/json"
IP_API_URL = "http://ip-api.com/json"


class GeolocationService:
    def __init__(self):
        self.attempts = {"freeipapi": deque(), "ip-api": deque()}
        self.blocked_until = {"freeipapi": 0.0, "ip-api": 0.0}
        self.locks = {name: Lock() for name in self.attempts}

    def _update_limits(self, provider, response):
        now = time.monotonic()
        if provider == "ip-api":
            remaining = response.headers.get("X-Rl")
            ttl = response.headers.get("X-Ttl")
            logger.info("ip-api X-Rl=%s X-Ttl=%s", remaining, ttl)
            try:
                remaining, ttl = int(remaining), int(ttl)
                if remaining < 0 or ttl < 0:
                    raise ValueError("Negative rate-limit header")
            except (TypeError, ValueError):
                # Unknown server budget: avoid another request for a full window.
                self.blocked_until[provider] = now + 60
            else:
                if remaining == 0:
                    self.blocked_until[provider] = now + ttl
        if response.status_code == 429:
            delay = 10 if provider == "freeipapi" else 60
            try:
                retry = float(response.headers.get("Retry-After", delay))
                if math.isfinite(retry) and retry >= 0:
                    delay = max(delay, retry)
            except ValueError:
                pass
            if provider != "ip-api" or self.blocked_until[provider] <= now:
                self.blocked_until[provider] = max(
                    self.blocked_until[provider], now + delay,
                )

    @staticmethod
    def _normalize(provider, data, requested_ip):
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object")
        if provider == "ip-api":
            if data.get("status") != "success":
                raise ValueError("ip-api lookup failed")
            fields = ("query", "lat", "lon", "country", "city", "isp")
        else:
            fields = ("ipAddress", "latitude", "longitude", "countryName", "cityName", "asnOrganization")
        result = dict(zip(
            ("ip", "latitude", "longitude", "country", "city", "isp"),
            (data.get(field) for field in fields),
        ))
        result["ip"] = result["ip"] if result["ip"] is not None else requested_ip
        if parse_ip(result["ip"]) != parse_ip(requested_ip):
            raise ValueError("Response IP does not match request")
        for field, limit in (("latitude", 90), ("longitude", 180)):
            value = result[field]
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or abs(value) > limit):
                raise ValueError(f"Invalid {field}")
        for field in ("country", "city"):
            if not isinstance(result[field], str):
                raise ValueError(f"Invalid {field}")
        if result["isp"] is not None and not isinstance(result["isp"], str):
            raise ValueError("Invalid isp")
        return result

    def resolve(self, ip_address):
        failure_status = 503
        for provider, url, limit, window in (
            ("freeipapi", FREE_IP_API_URL, 10, 10),
            ("ip-api", IP_API_URL, 45, 60),
        ):
            # Serialize ip-api calls so a zero-budget header cannot race a
            # second request. freeipapi only needs atomic slot reservation.
            lock = self.locks[provider]
            if not lock.acquire(blocking=False):
                continue
            locked = True
            try:
                now = time.monotonic()
                attempts = self.attempts[provider]
                while attempts and now - attempts[0] >= window:
                    attempts.popleft()
                if now < self.blocked_until[provider] or len(attempts) >= limit:
                    continue
                attempts.append(now)
                if provider == "freeipapi":
                    lock.release()
                    locked = False
                try:
                    response = httpx.get(f"{url}/{ip_address}", timeout=10.0)
                    if provider == "freeipapi":
                        with lock:
                            self._update_limits(provider, response)
                    else:
                        self._update_limits(provider, response)
                    response.raise_for_status()
                    return self._normalize(provider, response.json(), ip_address)
                except httpx.HTTPStatusError as exc:
                    # Includes 400, 403, 429, 500 and 503, plus other HTTP errors.
                    logger.warning("%s HTTP %s", provider, exc.response.status_code)
                    failure_status = 502
                except httpx.RequestError as exc:
                    logger.warning("%s request failed: %s", provider, type(exc).__name__)
                except (ValueError, TypeError, OverflowError) as exc:
                    logger.warning("%s invalid response: %s", provider, exc)
                    failure_status = 502
            finally:
                if locked:
                    lock.release()
        detail = (
            "Geolocation providers returned an error" if failure_status == 502
            else "Geolocation providers are unavailable"
        )
        raise HTTPException(status_code=failure_status, detail=detail)


geolocation_service = GeolocationService()


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "service-c"}


@app.get("/resolve-ip/{ip_address}")
def resolve_ip(ip_address: str):
    try:
        parse_ip(ip_address)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid IP address") from exc
    return geolocation_service.resolve(ip_address)
