from threading import Lock

from flask import Blueprint, current_app, jsonify, request


class UserStore:
    def __init__(self):
        self.users = {}
        self.lock = Lock()

    def check_or_create(self, email):
        with self.lock:
            exists = email in self.users
            if not exists:
                self.users[email] = {'email': email}
            return exists


users_bp = Blueprint('users', __name__)


@users_bp.post('/api/users/signin')
def signin():
    data = request.get_json(silent=True)
    email = data.get('email') if isinstance(data, dict) else None
    if not isinstance(email, str) or not email.strip():
        return jsonify({'error': 'email is required'}), 400
    exists = current_app.extensions['users'].check_or_create(email)
    return jsonify({'exists': exists, 'created': not exists}), 200 if exists else 201
