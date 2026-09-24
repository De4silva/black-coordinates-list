from statistics import median
from math import asin, cos, radians, sin, sqrt
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

    def to_dict(self):
        return {
            "id": self.id,
            "ip": self.ip,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "country": self.country,
            "city": self.city,
            "created_at": self.created_at.isoformat(),
            "status": self.status,
        }
def distance_km(first: Coordinate, second: Coordinate) -> float:
    lat1 = radians(first.latitude)
    lon1 = radians(first.longitude)
    lat2 = radians(second.latitude)
    lon2 = radians(second.longitude)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    value = (
        sin(dlat / 2) ** 2
        + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    )

    return 6371 * 2 * asin(sqrt(value))
def generate_clusters(records, max_distance_km=500):
    clusters = []

    for record in records:
        for cluster in clusters:
            if any(
                distance_km(record, member) <= max_distance_km
                for member in cluster
            ):
                cluster.append(record)
                break
        else:
            clusters.append([record])

    return clusters
def cluster_coordinates(cluster):
    longitudes = [record.longitude for record in cluster]
    latitudes = [record.latitude for record in cluster]

    mean_coordinates = [
        sum(longitudes) / len(longitudes),
        sum(latitudes) / len(latitudes),
    ]

    median_coordinates = [
        median(longitudes),
        median(latitudes),
    ]

    return median_coordinates, mean_coordinates