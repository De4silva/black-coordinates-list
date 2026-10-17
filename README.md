# Black Coordinates List

A distributed backend system for resolving IP addresses into geographic coordinates and storing intelligence data.

## Architecture

- Service A: FastAPI
- Service B: Flask + SQLAlchemy
- Database: SQLite
- Communication: HTTP REST

## Part 2: event driven user gateway

Flow: `POST /signin` on A -> Kafka `user-gateway` -> `kafka-consumer` ->
B `POST /api/users/signin`. Existing coordinate APIs, SQLite storage, and Service C
are unchanged.

Start with `docker compose up --build -d`. Kafka uses `apache/kafka:4.3.1` in
single-node KRaft mode, an internal broker listener on `kafka-broker:9092`, and
the named `kafka-data` volume. The one-shot `kafka-init` creates `user-gateway`
if missing (one partition, replication factor one). No host Kafka port is needed.

```http
POST http://localhost:8000/signin
Content-Type: application/json

{"email":"student@example.com","password":"optional","ip":"8.8.8.8"}
```

Email and IP are required and validated by Pydantic. Password is optional and is
never published or stored. A waits for broker acknowledgement and returns HTTP
202 with `{"message":"your request was received"}`. This acknowledges Kafka
receipt, not completion of processing by B. Invalid input returns 422, another
submission of the same normalized IP within 60 seconds returns 429, and Kafka
failure returns 503. Different emails still share the same IP limit.

The thread-safe IP guard uses monotonic time and reserves before publishing.
Failed publication retains the reservation because delivery can be uncertain;
retry after 60 seconds. Rejected duplicates do not extend the window. This guard
is process-local and resets on A restart; use the existing single-worker setup.

The Kafka value contains only `{"email":"student@example.com","ip":"8.8.8.8"}`;
email is the record key. The consumer uses `KAFKA_BOOTSTRAP_SERVERS=kafka-broker:9092`,
`KAFKA_TOPIC=user-gateway`, `KAFKA_GROUP_ID=user-gateway-group`, and
`SERVICE_B_URL=http://service-b:5000`.

B atomically checks or creates the email in an isolated, locked in-memory store:

```http
POST http://localhost:5000/api/users/signin
Content-Type: application/json

{"email":"student@example.com"}
```

New email: HTTP 201 `{"exists":false,"created":true}`. Existing email: HTTP 200
`{"exists":true,"created":false}`. This is the assignment's implicit signup/signin
distinction; it does not authenticate passwords or issue tokens. A validates email;
the consumer validates email/IP again before calling B. B requires a nonempty email.
User memory resets on B restart and is not shared across processes. Coordinate
records remain in the existing SQLite volume.

Offsets are committed only after B returns HTTP 200/201 with the expected boolean
`exists`/`created` values matching that status. Network failures, HTTP 408/429, and 5xx
responses retry the same event every second. Malformed events are logged by
partition/offset and deliberately skipped with an offset commit. Other HTTP errors
and malformed or unexpected successful responses are logged and stop the consumer
without committing that event. Compose restarts the consumer on failure, replaying
the uncommitted event; a persistent error continues retrying until its cause is fixed.
The consumer processes one record at a time. Kafka failures (including lost group
membership after a long outage) close the client and reconnect from committed
offsets after two seconds. Delivery is at least once: redelivery cannot create a second
user for the same email while B's memory remains intact. No dead-letter service
or additional infrastructure is introduced.

### Two additional possible subscribers (documented examples only)

- **Audit logging consumer:** record accepted sign-in requests for an audit trail.
- **Sign-in analytics consumer:** aggregate request counts and IP usage statistics.

Each would use its own group (for example `user-audit-group` and
`user-analytics-group`) so each receives the same topic events independently.
Consumers sharing one group divide the work; they do not each receive every event.
These examples are not implemented as services.

### Tests

Run from the root with the existing virtual environment (install A/B and consumer
requirements first). Run suites separately because A and B both name their package
`app`; the B tests and storage regression use isolated memory, not local SQLite.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_signin.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_users.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_kafka_consumer.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_geolocation.py -v
```

`test_users.py` includes a coordinate storage isolation regression. The existing
untracked `tests/storage_smoke.py` can additionally exercise full coordinate CRUD
locally with `.\.venv\Scripts\python.exe tests/storage_smoke.py -v`.
For isolated Docker verification, use a separate Compose
project (ensure host ports 8000/5000/8001 are free):

```powershell
docker compose -p black-coordinates-part2-check config --quiet
docker compose -p black-coordinates-part2-check up --build -d
.\.venv\Scripts\python.exe tests/event_flow_integration.py
docker compose -p black-coordinates-part2-check exec -T kafka-broker /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka-broker:9092 --describe --topic user-gateway
docker compose -p black-coordinates-part2-check down
```

The integration script checks health, topic configuration, publishes a unique
email through A, confirms duplicate-IP rejection, waits for the consumer's group
offset to catch up, then verifies B reports the email already exists. It does not
create users while polling. Separate project names isolate volumes; never use
`down -v` on the existing deployment. Normal `down` retains the verification volumes.
