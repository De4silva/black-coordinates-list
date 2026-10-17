import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from kafka.errors import CommitFailedError

import httpx

spec = importlib.util.spec_from_file_location('consumer_main', Path(__file__).resolve().parents[1] / 'kafka-consumer/main.py')
consumer_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(consumer_main)


class ConsumerTests(unittest.TestCase):
    def setUp(self):
        self.message = SimpleNamespace(value=b'{"email":"student@example.com","ip":"8.8.8.8"}', partition=0, offset=1)
        self.consumer = Mock()
        self.client = Mock()
        self.sleep = Mock()

    def response(self, status):
        return httpx.Response(status, json={'exists': status == 200, 'created': status == 201}, request=httpx.Request('POST', 'http://service-b/api/users/signin'))

    def test_success_commits_after_http(self):
        def post(*args, **kwargs):
            self.consumer.commit.assert_not_called()
            return self.response(201)
        self.client.post.side_effect = post
        consumer_main.process_message(self.message, self.consumer, self.client)
        self.client.post.assert_called_once_with('/api/users/signin', json={'email': 'student@example.com'})
        self.consumer.commit.assert_called_once()

    def test_temporary_failures_retry_without_commit(self):
        replies = [httpx.ConnectError('offline'), self.response(503), self.response(429), self.response(200)]
        self.client.post.side_effect = replies
        self.sleep.side_effect = lambda _: self.consumer.commit.assert_not_called()
        consumer_main.process_message(self.message, self.consumer, self.client, self.sleep)
        self.assertEqual(self.client.post.call_count, 4)
        self.assertEqual(self.sleep.call_count, 3)
        self.consumer.commit.assert_called_once()

    def test_malformed_events_logged_and_skipped(self):
        for value in (None, b'bad', b'[]', b'{}', b'{"email":"bad","ip":"8.8.8.8"}',
                      b'{"email":"student@example.com","ip":"invalid"}', b'\xff'):
            self.consumer.reset_mock()
            self.message.value = value
            with self.assertLogs(consumer_main.logger, level='ERROR'):
                consumer_main.process_message(self.message, self.consumer, self.client)
            self.consumer.commit.assert_called_once()
        self.client.post.assert_not_called()

    def test_permanent_failure_does_not_commit(self):
        self.client.post.return_value = self.response(400)
        with self.assertLogs(consumer_main.logger, level='ERROR') as logs, self.assertRaises(httpx.HTTPStatusError):
            consumer_main.process_message(self.message, self.consumer, self.client)
        self.consumer.commit.assert_not_called()
        self.assertIn('status=400 partition=0 offset=1', logs.output[0])
        self.assertIn('uncommitted', logs.output[0])

    def test_invalid_successful_responses_do_not_commit(self):
        invalid = [(200, []), (200, None), (200, {}), (201, {'created': True}),
                   (200, {'exists': 1, 'created': 0}),
                   (200, {'exists': True, 'created': True}),
                   (201, {'exists': True, 'created': False}),
                   (202, {'exists': False, 'created': True}),
                   (204, {'exists': True, 'created': False})]
        replies = [httpx.Response(status, json=body, request=httpx.Request('POST', 'http://service-b'))
                   for status, body in invalid]
        replies.append(httpx.Response(200, content=b'not JSON', request=httpx.Request('POST', 'http://service-b')))
        for response in replies:
            with self.subTest(status=response.status_code, body=response.content):
                self.client.post.return_value = response
                with self.assertLogs(consumer_main.logger, level='ERROR') as logs, self.assertRaises(ValueError):
                    consumer_main.process_message(self.message, self.consumer, self.client)
                self.consumer.commit.assert_not_called()
                self.assertIn('Invalid Service B response', logs.output[0])
                self.assertIn('uncommitted', logs.output[0])

    def test_json_is_validated_before_commit(self):
        for status in (200, 201):
            with self.subTest(status=status):
                self.consumer.reset_mock()
                response = self.response(status)
                original_json = response.json
                def decode():
                    self.consumer.commit.assert_not_called()
                    return original_json()
                with patch.object(response, 'json', side_effect=decode) as decode_json:
                    self.client.post.return_value = response
                    consumer_main.process_message(self.message, self.consumer, self.client)
                    decode_json.assert_called_once()
                self.consumer.commit.assert_called_once()

    def test_permanent_failure_closes_consumer_and_exits_for_restart(self):
        self.consumer.__iter__ = Mock(return_value=iter([self.message]))
        self.client.post.return_value = self.response(403)
        client_context = Mock()
        client_context.__enter__ = Mock(return_value=self.client)
        client_context.__exit__ = Mock(return_value=False)
        with patch.object(consumer_main, 'KafkaConsumer', return_value=self.consumer), \
                patch.object(consumer_main.httpx, 'Client', return_value=client_context), \
                self.assertLogs(consumer_main.logger, level='ERROR'), \
                self.assertRaises(httpx.HTTPStatusError):
            consumer_main.main()
        self.consumer.commit.assert_not_called()
        self.consumer.close.assert_called_once()

    def test_commit_failure_reconnects_for_redelivery(self):
        self.client.post.return_value = self.response(201)
        self.consumer.commit.side_effect = CommitFailedError()
        with self.assertRaises(CommitFailedError):
            consumer_main.process_message(self.message, self.consumer, self.client)
        with patch.object(consumer_main, 'consume', side_effect=[CommitFailedError(), KeyboardInterrupt()]) as consume, \
                patch.object(consumer_main.time, 'sleep') as sleep:
            with self.assertLogs(consumer_main.logger, level='ERROR'), self.assertRaises(KeyboardInterrupt):
                consumer_main.main()
            self.assertEqual(consume.call_count, 2)
            sleep.assert_called_once_with(2)


if __name__ == '__main__':
    unittest.main()
