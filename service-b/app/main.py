from pathlib import Path

from flask import Flask

from app.database import db
from app.models import Coordinate
from app.routes import coordinates_bp
from app.users import UserStore, users_bp


BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_PATH = BASE_DIR / "instance" / "coordinates.db"


def create_app():
    app = Flask(__name__)

    app.config["SQLALCHEMY_DATABASE_URI"] = (
        f"sqlite:///{DATABASE_PATH.as_posix()}"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    app.register_blueprint(coordinates_bp)
    app.extensions['users'] = UserStore()
    app.register_blueprint(users_bp)

    with app.app_context():
        db.create_all()

    @app.get("/health")
    def health_check():
        return {
            "status": "ok",
            "service": "service-b",
        }

    return app


app = create_app()
