from datetime import datetime, timezone

from app.database import db


class Coordinate(db.Model):
    __tablename__ = "coordinates"

    id = db.Column(db.Integer, primary_key=True)
    ip = db.Column(db.String(45), nullable=False, index=True)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    country = db.Column(db.String(100), nullable=True, index=True)
    city = db.Column(db.String(100), nullable=True)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    status = db.Column(
        db.String(20),
        nullable=False,
        default="active",
    )