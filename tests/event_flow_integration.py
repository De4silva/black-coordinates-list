"""Explicit Docker check; run only against the isolated verification stack."""
import json
import subprocess
import time
import uuid

import httpx


COMPOSE = ['docker', 'compose', '-p', 'black-coordinates-part2-check']


def broker(*args):
    return subprocess.check_output(
        COMPOSE + ['exec', '-T', 'kafka-broker'] + list(args), text=True, timeout=20)


def main():
    with httpx.Client(timeout=10) as client:
        for port in (8000, 5000, 8001):
            deadline = time.monotonic() + 30
            while True:
                try:
                    client.get(f'http://localhost:{port}/health').raise_for_status()
                    break
                except httpx.HTTPError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(1)
        topic = broker('/opt/kafka/bin/kafka-topics.sh', '--bootstrap-server',
                       'kafka-broker:9092', '--describe', '--topic', 'user-gateway')
        assert 'PartitionCount: 1' in topic and 'ReplicationFactor: 1' in topic, topic
        print(topic)
        email = f'check-{uuid.uuid4().hex}@example.com'
        # Different IP on every run, without depending on external geolocation.
        ip = f'2001:db8::{uuid.uuid4().int & 0xffff:x}'
        result = client.post('http://localhost:8000/signin', json={'email': email, 'ip': ip})
        assert result.status_code == 202, result.text
        assert result.json() == {'message': 'your request was received'}
        duplicate = client.post('http://localhost:8000/signin', json={'email': email, 'ip': ip})
        assert duplicate.status_code == 429, duplicate.text
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            groups = broker('/opt/kafka/bin/kafka-consumer-groups.sh', '--bootstrap-server',
                            'kafka-broker:9092', '--describe', '--group', 'user-gateway-group')
            rows = [line.split() for line in groups.splitlines() if 'user-gateway ' in line]
            if rows and all(row[5] == '0' and row[3] != '-' for row in rows):
                break
            time.sleep(1)
        else:
            raise AssertionError('Consumer did not commit the event within 90 seconds')
        found = client.post('http://localhost:5000/api/users/signin', json={'email': email})
        assert found.status_code == 200, found.text
        assert found.json() == {'exists': True, 'created': False}, found.text
        print(json.dumps({'flow': 'PASS', 'duplicate_ip': 'PASS', 'existing_user': 'PASS'}))


if __name__ == '__main__':
    main()
