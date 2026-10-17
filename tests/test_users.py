from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import unittest

from flask import Flask

# Run separately from A's tests: both existing services use the package name app.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'service-b'))
from app.users import UserStore, users_bp
from app.database import db
from app.routes import coordinates_bp


class UserTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.extensions['users'] = UserStore()
        self.app.register_blueprint(users_bp)
        self.client = self.app.test_client()

    def test_atomic_check_or_create(self):
        first = self.client.post('/api/users/signin', json={'email': 'student@example.com'})
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json, {'exists': False, 'created': True})
        second = self.client.post('/api/users/signin', json={'email': 'student@example.com'})
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json, {'exists': True, 'created': False})
        self.assertEqual(len(self.app.extensions['users'].users), 1)

    def test_concurrency_and_reset(self):
        store = self.app.extensions['users']
        with ThreadPoolExecutor(max_workers=12) as executor:
            existing = list(executor.map(store.check_or_create, ['student@example.com'] * 12))
        self.assertEqual(existing.count(False), 1)
        self.assertEqual(len(store.users), 1)
        self.assertFalse(UserStore().check_or_create('student@example.com'))

    def test_invalid_body(self):
        for value in ({}, [], {'email': ''}, {'email': 123}):
            self.assertEqual(self.client.post('/api/users/signin', json=value).status_code, 400)

    def test_users_do_not_change_coordinate_storage(self):
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        db.init_app(self.app)
        self.app.register_blueprint(coordinates_bp)
        with self.app.app_context():
            db.create_all()
            try:
                data = dict(ip='8.8.8.8', latitude=37.4, longitude=-122.1,
                            country='United States', city='Mountain View')
                saved = self.client.post('/api/coordinates', json=data)
                self.assertEqual(saved.status_code, 201)
                self.client.post('/api/users/signin', json={'email': 'student@example.com'})
                self.assertEqual(self.client.get('/api/coordinates').json, [saved.json])
            finally:
                db.session.remove()
                db.drop_all()


if __name__ == '__main__':
    unittest.main()
