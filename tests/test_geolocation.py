import importlib.util
import os
from pathlib import Path
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("geolocation", ROOT / "service-c/main.py")
geo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(geo)
IP = "8.8.8.8"
FREE = dict(ipAddress=IP, latitude=37.4, longitude=-122.1,
            countryName="United States", cityName="Mountain View", asnOrganization="Google")
OTHER = dict(status="success", query=IP, lat=37.4, lon=-122.1,
             country="United States", city="Mountain View", isp="Google")
EXPECTED = dict(ip=IP, latitude=37.4, longitude=-122.1,
                country="United States", city="Mountain View", isp="Google")


def response(provider="freeipapi", status=200, data=None, headers=None):
    return httpx.Response(status, json=data if data is not None else (FREE if provider == "freeipapi" else OTHER),
                          headers=headers if headers is not None else {"X-Rl": "44", "X-Ttl": "60"},
                          request=httpx.Request("GET", "http://provider/"))


class GeolocationTests(unittest.TestCase):
    def setUp(self):
        self.service = geo.GeolocationService()
        self.clock = patch.object(geo.time, "monotonic", return_value=100.0)
        self.now = self.clock.start()
        self.addCleanup(self.clock.stop)

    def test_free_success(self):
        with patch.object(geo.httpx, "get", return_value=response()) as get:
            self.assertEqual(self.service.resolve(IP), EXPECTED)
            self.assertEqual(get.call_count, 1)
            self.assertEqual(get.call_args.args[0], f"{geo.FREE_IP_API_URL}/{IP}")

    def test_free_limit_fallback_and_reset(self):
        def get(url, **kwargs):
            return response("ip-api" if url.startswith(geo.IP_API_URL) else "freeipapi")
        with patch.object(geo.httpx, "get", side_effect=get) as mock:
            for _ in range(11):
                self.assertEqual(self.service.resolve(IP), EXPECTED)
            self.assertEqual(sum(c.args[0].startswith(geo.FREE_IP_API_URL) for c in mock.call_args_list), 10)
            self.now.return_value = 110
            self.service.resolve(IP)
            self.assertTrue(mock.call_args.args[0].startswith(geo.FREE_IP_API_URL))

    def test_ip_headers_logged_and_cooldown_expires(self):
        self.service.blocked_until["freeipapi"] = 1000
        with patch.object(geo.httpx, "get", return_value=response("ip-api", headers={"X-Rl": "0", "X-Ttl": "7"})) as get:
            with self.assertLogs("uvicorn.error", level="INFO") as logs:
                self.assertEqual(self.service.resolve(IP), EXPECTED)
            self.assertIn("X-Rl=0 X-Ttl=7", logs.output[0])
            self.now.return_value = 106.999
            with self.assertRaises(geo.HTTPException) as error:
                self.service.resolve(IP)
            self.assertEqual(error.exception.status_code, 503)
            self.assertEqual(get.call_count, 1)
            self.now.return_value = 107
            self.service.resolve(IP)
            self.assertEqual(get.call_count, 2)

    def test_ip_cooldown_falls_back_to_free(self):
        self.service.blocked_until["freeipapi"] = 101
        with patch.object(geo.httpx, "get", side_effect=[response("ip-api", headers={"X-Rl": "0", "X-Ttl": "30"}), response()]) as get:
            self.service.resolve(IP)
            self.now.return_value = 101
            self.assertEqual(self.service.resolve(IP), EXPECTED)
            self.assertTrue(get.call_args.args[0].startswith(geo.FREE_IP_API_URL))

    def test_ip_local_limit_even_without_zero_header(self):
        self.service.blocked_until["freeipapi"] = 1000
        with patch.object(geo.httpx, "get", return_value=response("ip-api")) as get:
            for _ in range(45):
                self.service.resolve(IP)
            with self.assertRaises(geo.HTTPException):
                self.service.resolve(IP)
            self.assertEqual(get.call_count, 45)
            self.now.return_value = 160
            self.service.resolve(IP)
            self.assertEqual(get.call_count, 46)

    def test_http_errors_fallback_and_exhaustion(self):
        for provider in ("freeipapi", "ip-api"):
            for status in (400, 403, 429, 500, 503):
                with self.subTest(provider=provider, status=status):
                    service = geo.GeolocationService()
                    if provider == "ip-api":
                        first = response(status=500)
                        second = response("ip-api", status=status)
                    else:
                        first = response(status=status)
                        second = response("ip-api")
                    with patch.object(geo.httpx, "get", side_effect=[first, second]) as get:
                        with self.assertLogs("uvicorn.error", level="INFO") as logs:
                            if provider == "freeipapi":
                                self.assertEqual(service.resolve(IP), EXPECTED)
                            else:
                                with self.assertRaises(geo.HTTPException) as error:
                                    service.resolve(IP)
                                self.assertEqual(error.exception.status_code, 502)
                        self.assertEqual(get.call_count, 2)
                        self.assertTrue(any(f"{provider} HTTP {status}" in line for line in logs.output))
                        self.assertTrue(any("X-Rl=44 X-Ttl=60" in line for line in logs.output))

    def test_free_429_cooldown(self):
        with patch.object(geo.httpx, "get", side_effect=[response(status=429, headers={"Retry-After": "20"}), response("ip-api"), response("ip-api")]) as get:
            self.service.resolve(IP)
            self.service.resolve(IP)
            self.assertEqual(self.service.blocked_until["freeipapi"], 120)
            self.assertTrue(get.call_args.args[0].startswith(geo.IP_API_URL))

    def test_ip_429_headers_block_before_retry(self):
        self.service.blocked_until["freeipapi"] = 1000
        with patch.object(geo.httpx, "get", return_value=response("ip-api", status=429, headers={"X-Rl": "0", "X-Ttl": "12"})) as get:
            for _ in range(2):
                with self.assertRaises(geo.HTTPException):
                    self.service.resolve(IP)
            self.assertEqual(get.call_count, 1)
            self.assertEqual(self.service.blocked_until["ip-api"], 112)

    def test_network_errors(self):
        for cls in (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout):
            with self.subTest(error=cls.__name__):
                with patch.object(geo.httpx, "get", side_effect=[cls("failure"), response("ip-api")]):
                    self.assertEqual(geo.GeolocationService().resolve(IP), EXPECTED)
                with patch.object(geo.httpx, "get", side_effect=cls("failure")):
                    with self.assertRaises(geo.HTTPException) as error:
                        geo.GeolocationService().resolve(IP)
                    self.assertEqual(error.exception.status_code, 503)

    def test_malformed_responses(self):
        for provider, good in (("freeipapi", FREE), ("ip-api", OTHER)):
            lat = "lat" if provider == "ip-api" else "latitude"
            bad = [[], {}, {**good, lat: None}, {**good, lat: True},
                   {**good, lat: float("inf")}, {**good, lat: 91},
                   {**good, ("query" if provider == "ip-api" else "ipAddress"): "1.1.1.1"}]
            if provider == "ip-api":
                bad.append({"status": "fail", "message": "private range"})
            malformed = httpx.Response(200, content=b"not JSON", request=httpx.Request("GET", "http://provider/"))
            replies = [response(provider, data=data) for data in bad if not (isinstance(data, dict) and any(isinstance(v, float) and v == float("inf") for v in data.values()))]
            replies.append(malformed)
            for reply in replies:
                with self.subTest(provider=provider, body=reply.content):
                    service = geo.GeolocationService()
                    sequence = [reply, response("ip-api")] if provider == "freeipapi" else [response(status=500), reply]
                    with patch.object(geo.httpx, "get", side_effect=sequence):
                        if provider == "freeipapi":
                            self.assertEqual(service.resolve(IP), EXPECTED)
                        else:
                            with self.assertRaises(geo.HTTPException) as error:
                                service.resolve(IP)
                            self.assertEqual(error.exception.status_code, 502)
            with self.assertRaises(ValueError):
                geo.GeolocationService._normalize(provider, {**good, lat: float("inf")}, IP)

    def test_invalid_headers_are_conservative(self):
        for headers in ({}, {"X-Rl": "bad", "X-Ttl": "NaN"}, {"X-Rl": "0", "X-Ttl": "-1"}):
            service = geo.GeolocationService()
            service.blocked_until["freeipapi"] = 1000
            with patch.object(geo.httpx, "get", return_value=response("ip-api", headers=headers)) as get:
                service.resolve(IP)
                with self.assertRaises(geo.HTTPException):
                    service.resolve(IP)
                self.assertEqual(get.call_count, 1)
                self.assertEqual(service.blocked_until["ip-api"], 160)

    def test_concurrent_request_uses_other_provider(self):
        entered, release = Event(), Event()
        self.service.attempts["freeipapi"].extend([100] * 9)
        def get(url, **kwargs):
            if url.startswith(geo.FREE_IP_API_URL):
                entered.set()
                self.assertTrue(release.wait(5))
                return response()
            return response("ip-api", headers={"X-Rl": "0", "X-Ttl": "10"})
        with patch.object(geo.httpx, "get", side_effect=get) as mock:
            with ThreadPoolExecutor(max_workers=2) as executor:
                future = executor.submit(self.service.resolve, IP)
                try:
                    self.assertTrue(entered.wait(5))
                    self.assertEqual(self.service.resolve(IP), EXPECTED)
                    with self.assertRaises(geo.HTTPException):
                        self.service.resolve(IP)
                    self.assertEqual(mock.call_count, 2)
                finally:
                    release.set()
                self.assertEqual(future.result(), EXPECTED)

    def test_c_endpoints(self):
        client = TestClient(geo.app)
        with patch.object(geo, "geolocation_service", self.service), patch.object(geo.httpx, "get", return_value=response()) as get:
            self.assertEqual(client.get("/health").json(), {"status": "ok", "service": "service-c"})
            self.assertEqual(client.get(f"/resolve-ip/{IP}").json(), EXPECTED)
            self.assertEqual(client.get("/resolve-ip/invalid").status_code, 400)
            self.assertEqual(get.call_count, 1)
        with patch.object(geo, "geolocation_service", geo.GeolocationService()), patch.object(geo.httpx, "get", side_effect=httpx.ReadTimeout("timeout")):
            self.assertEqual(client.get(f"/resolve-ip/{IP}").status_code, 503)
        with patch.object(geo, "geolocation_service", geo.GeolocationService()), patch.object(geo.httpx, "get", return_value=response(status=403)):
            self.assertEqual(client.get(f"/resolve-ip/{IP}").status_code, 502)

    def test_concurrent_free_limit_reservations(self):
        release = Event()
        self.service.blocked_until["ip-api"] = 1000
        def get(url, **kwargs):
            self.assertTrue(release.wait(5))
            return response()
        def resolve():
            try:
                return self.service.resolve(IP)
            except geo.HTTPException as exc:
                return exc.status_code
        with patch.object(geo.httpx, "get", side_effect=get) as mock:
            with ThreadPoolExecutor(max_workers=12) as executor:
                futures = [executor.submit(resolve) for _ in range(12)]
                release.set()
                results = [future.result() for future in futures]
            self.assertEqual(mock.call_count, 10)
            self.assertEqual(results.count(EXPECTED), 10)
            self.assertEqual(results.count(503), 2)


class ExistingFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("SERVICE_C_URL", "http://service-c:8001")
        sys.path.insert(0, str(ROOT / "service-a"))
        from app.main import app
        from app import routes
        cls.routes = routes
        cls.client = TestClient(app)

    def test_single_and_list_resolve_and_save(self):
        def get(url, **kwargs):
            result = geo.GeolocationService().resolve(IP)
            return httpx.Response(200, json=result, request=httpx.Request("GET", url))
        original_get = geo.httpx.get
        # Service A and C share httpx; route C's external calls separately.
        def route_get(url, **kwargs):
            if "service-c" in url:
                with patch.object(geo.httpx, "get", return_value=response()):
                    return get(url, **kwargs)
            return original_get(url, **kwargs)
        saved = {**{k: v for k, v in EXPECTED.items() if k != "isp"}, "id": 1, "status": "active"}
        with patch.object(geo.httpx, "get", side_effect=route_get), patch.object(geo.httpx, "post", return_value=httpx.Response(201, json=saved, request=httpx.Request("POST", "http://service-b"))) as post:
            self.assertEqual(self.client.post("/resolve-ip", json={"ip": IP}).json(), {"location": EXPECTED, "saved_coordinate": saved})
            result = self.client.post("/resolve-ip-list", json={"ips": [IP, IP]})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(len(result.json()), 2)
            self.assertEqual(post.call_count, 3)
            self.assertNotIn("isp", post.call_args.kwargs["json"])
        self.assertEqual(self.client.post("/resolve-ip", json={"ip": "bad"}).status_code, 422)

    def test_a_preserves_upstream_error_mapping(self):
        for path, body in (("/resolve-ip", {"ip": IP}), ("/resolve-ip-list", {"ips": [IP]})):
            for status in (502, 503):
                with patch.object(geo.httpx, "get", return_value=response(status=status)):
                    result = self.client.post(path, json=body)
                self.assertEqual(result.status_code, 502)
                self.assertEqual(result.json(), {"detail": "Upstream service returned an error"})


if __name__ == "__main__":
    unittest.main()
