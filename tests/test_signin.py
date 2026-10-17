from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from kafka.errors import KafkaTimeoutError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'service-a'))
from app.main import app
from app.user_gateway import DuplicateIP, UserGateway


class SigninTests(unittest.TestCase):
    def setUp(self):
        self.gateway = UserGateway()
        self.gateway.producer = Mock()
        self.client = TestClient(app)
        self.route_patch = patch('app.routes.user_gateway', self.gateway)
        self.route_patch.start()
        self.addCleanup(self.route_patch.stop)
        self.body = {'email': 'student@example.com', 'ip': '8.8.8.8'}

    def test_validation(self):
        for body in ({}, {'email': 'bad', 'ip': '8.8.8.8'},
                     {'email': 'student@example.com', 'ip': 'bad'},
                     {'email': 'student@example.com'}, {'ip': '8.8.8.8'},
                     {**self.body, 'password': 123}):
            with self.subTest(body=body):
                self.assertEqual(self.client.post('/signin', json=body).status_code, 422)
        self.gateway.producer.send.assert_not_called()

    def test_acknowledged_event_without_password(self):
        result = self.client.post('/signin', json={**self.body, 'password': 'secret'})
        self.assertEqual(result.status_code, 202)
        self.assertEqual(result.json(), {'message': 'your request was received'})
        self.gateway.producer.send.assert_called_once_with(
            'user-gateway', key=self.body['email'], value=self.body)
        self.gateway.producer.send.return_value.get.assert_called_once_with(timeout=15)

    def test_duplicate_boundary_and_different_ips(self):
        with patch('app.user_gateway.time.monotonic', return_value=100) as clock:
            self.assertEqual(self.client.post('/signin', json=self.body).status_code, 202)
            clock.return_value = 159.999
            self.assertEqual(self.client.post('/signin', json={**self.body, 'email': 'other@example.com'}).status_code, 429)
            self.assertEqual(self.client.post('/signin', json={**self.body, 'ip': '1.1.1.1'}).status_code, 202)
            clock.return_value = 160
            self.assertEqual(self.client.post('/signin', json=self.body).status_code, 202)

    def test_broker_failure_is_not_accepted(self):
        self.gateway.producer.send.return_value.get.side_effect = KafkaTimeoutError()
        self.assertEqual(self.client.post('/signin', json=self.body).status_code, 503)
        self.assertEqual(self.client.post('/signin', json=self.body).status_code, 429)

    def test_concurrent_same_ip_only_publishes_once(self):
        def submit(_):
            try:
                self.gateway.publish('student@example.com', '8.8.8.8')
                return True
            except DuplicateIP:
                return False
        with ThreadPoolExecutor(max_workers=12) as executor:
            self.assertEqual(sum(executor.map(submit, range(12))), 1)
        self.gateway.producer.send.assert_called_once()

    def test_ipv6_is_normalized(self):
        first = {**self.body, 'ip': '2001:0db8:0:0:0:0:0:1'}
        second = {**self.body, 'ip': '2001:db8::1'}
        self.assertEqual(self.client.post('/signin', json=first).status_code, 202)
        self.assertEqual(self.client.post('/signin', json=second).status_code, 429)


if __name__ == '__main__':
    unittest.main()
