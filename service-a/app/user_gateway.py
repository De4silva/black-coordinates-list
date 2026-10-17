import json
import os
import time
from threading import Lock

from kafka import KafkaProducer


class DuplicateIP(Exception):
    pass


class UserGateway:
    def __init__(self):
        self.lock = Lock()
        self.reservations = {}
        self.producer = None

    def publish(self, email, ip):
        with self.lock:
            now = time.monotonic()
            self.reservations = {
                address: deadline for address, deadline in self.reservations.items()
                if deadline > now
            }
            if ip in self.reservations:
                raise DuplicateIP()
            # Reserve before network I/O so concurrent requests cannot both publish.
            self.reservations[ip] = now + 60
        with self.lock:
            if self.producer is None:
                self.producer = KafkaProducer(
                    bootstrap_servers=os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092').split(','),
                    acks='all',
                    max_block_ms=10000,
                    request_timeout_ms=10000,
                    value_serializer=lambda value: json.dumps(value).encode('utf-8'),
                    key_serializer=lambda value: value.encode('utf-8'),
                )
            producer = self.producer
        # Retain the reservation on failure: delivery may be uncertain after
        # a timeout. B's atomic check-or-create handles redelivery.
        producer.send(
            os.getenv('KAFKA_TOPIC', 'user-gateway'),
            key=email, value={'email': email, 'ip': ip},
        ).get(timeout=15)

    def close(self):
        if self.producer is not None:
            self.producer.close(timeout=5)


user_gateway = UserGateway()
