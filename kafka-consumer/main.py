import json
import logging
import os
import time
from ipaddress import ip_address

import httpx
from email_validator import validate_email, EmailNotValidError
from kafka import KafkaConsumer
from kafka.errors import KafkaError


logger = logging.getLogger(__name__)


def decode_event(value):
    event = json.loads(value)
    if not isinstance(event, dict) or not isinstance(event.get('email'), str):
        raise ValueError('Expected email and IP')
    validate_email(event['email'], check_deliverability=False)
    if not isinstance(event.get('ip'), str):
        raise ValueError('Expected IP string')
    ip_address(event['ip'])
    return event


def process_message(message, consumer, client, sleep=time.sleep):
    try:
        event = decode_event(message.value)
    except (ValueError, TypeError, UnicodeError, EmailNotValidError):
        logger.error('Skipping malformed event partition=%s offset=%s', message.partition, message.offset)
        consumer.commit()
        return
    while True:
        try:
            response = client.post('/api/users/signin', json={'email': event['email']})
            response.raise_for_status()
            try:
                result = response.json()
                expected = {200: (True, False), 201: (False, True)}
                if (response.status_code not in expected or not isinstance(result, dict)
                        or type(result.get('exists')) is not bool
                        or type(result.get('created')) is not bool
                        or (result['exists'], result['created']) != expected[response.status_code]):
                    raise ValueError('Unexpected Service B response structure')
            except ValueError:
                logger.error('Invalid Service B response status=%s partition=%s offset=%s; '
                             'event remains uncommitted', response.status_code,
                             message.partition, message.offset)
                raise
            consumer.commit()
            logger.info('Processed event partition=%s offset=%s created=%s',
                        message.partition, message.offset, result['created'])
            return
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500 and exc.response.status_code not in (408, 429):
                # Leave offset uncommitted; stop rather than silently lose a valid event.
                logger.error('Permanent Service B failure status=%s partition=%s offset=%s; '
                             'event remains uncommitted', exc.response.status_code,
                             message.partition, message.offset)
                raise
        except httpx.RequestError:
            pass
        logger.warning('Service B unavailable; retrying partition=%s offset=%s', message.partition, message.offset)
        sleep(1)


def consume():
    consumer = KafkaConsumer(
        os.getenv('KAFKA_TOPIC', 'user-gateway'),
        bootstrap_servers=os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka-broker:9092').split(','),
        group_id=os.getenv('KAFKA_GROUP_ID', 'user-gateway-group'),
        enable_auto_commit=False,
        auto_offset_reset='earliest',
        max_poll_records=1,
    )
    try:
        with httpx.Client(base_url=os.getenv('SERVICE_B_URL', 'http://service-b:5000'), timeout=10) as client:
            for message in consumer:
                process_message(message, consumer, client)
    finally:
        consumer.close()


def main():
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            consume()
            return
        except KafkaError:
            # Rejoin from committed offsets after a broker outage or lost
            # membership. B tolerates replay if processing preceded a failed commit.
            logger.exception('Kafka consumer failed; reconnecting from committed offsets')
            time.sleep(2)


if __name__ == '__main__':
    main()
