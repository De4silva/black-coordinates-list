from flask import Blueprint, jsonify, request

from app.database import db
from app.models import Coordinate


coordinates_bp = Blueprint("coordinates", __name__)


@coordinates_bp.post("/api/coordinates")
def create_coordinate():
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"error": "JSON body is required"}), 400

    required_fields = [
        "ip",
        "latitude",
        "longitude",
        "country",
        "city",
    ]

    missing_fields = [
        field for field in required_fields if data.get(field) is None
    ]

    if missing_fields:
        return jsonify({
            "error": "Missing required fields",
            "fields": missing_fields,
        }), 400

    coordinate = Coordinate(
        ip=data["ip"],
        latitude=data["latitude"],
        longitude=data["longitude"],
        country=data["country"],
        city=data["city"],
        status=data.get("status", "active"),
    )

    try:
        db.session.add(coordinate)
        db.session.commit()

    except Exception:
        db.session.rollback()

        return jsonify({
            "error": "Failed to save coordinate",
        }), 500

    return jsonify({
        "id": coordinate.id,
        "ip": coordinate.ip,
        "latitude": coordinate.latitude,
        "longitude": coordinate.longitude,
        "country": coordinate.country,
        "city": coordinate.city,
        "created_at": coordinate.created_at.isoformat(),
        "status": coordinate.status,
    }), 201

@coordinates_bp.get("/api/coordinates")
def get_coordinates():
    country = request.args.get("country")
    ip_address = request.args.get("ip")

    query = Coordinate.query

    if country:
        query = query.filter_by(country=country)

    if ip_address:
        query = query.filter_by(ip=ip_address)

    coordinates = query.order_by(Coordinate.id).all()

    result = []

    for coordinate in coordinates:
        result.append({
            "id": coordinate.id,
            "ip": coordinate.ip,
            "latitude": coordinate.latitude,
            "longitude": coordinate.longitude,
            "country": coordinate.country,
            "city": coordinate.city,
            "created_at": coordinate.created_at.isoformat(),
            "status": coordinate.status,
        })

    return jsonify(result), 200

@coordinates_bp.put("/api/coordinates/<int:coordinate_id>")
def update_coordinate(coordinate_id):
    coordinate = db.session.get(Coordinate, coordinate_id)

    if coordinate is None:
        return jsonify({
            "error": "Coordinate not found",
        }), 404

    data = request.get_json(silent=True)

    if not data:
        return jsonify({
            "error": "JSON body is required",
        }), 400

    allowed_statuses = {
        "active",
        "verified",
        "archived",
    }

    new_status = data.get("status")

    if new_status not in allowed_statuses:
        return jsonify({
            "error": "Invalid status",
            "allowed_statuses": sorted(allowed_statuses),
        }), 400

    coordinate.status = new_status

    try:
        db.session.commit()

    except Exception:
        db.session.rollback()

        return jsonify({
            "error": "Failed to update coordinate",
        }), 500

    return jsonify({
        "id": coordinate.id,
        "ip": coordinate.ip,
        "latitude": coordinate.latitude,
        "longitude": coordinate.longitude,
        "country": coordinate.country,
        "city": coordinate.city,
        "created_at": coordinate.created_at.isoformat(),
        "status": coordinate.status,
    }), 200

@coordinates_bp.delete("/api/coordinates/<int:coordinate_id>")
def delete_coordinate(coordinate_id):
    coordinate = db.session.get(Coordinate, coordinate_id)

    if coordinate is None:
        return jsonify({
            "error": "Coordinate not found",
        }), 404

    try:
        db.session.delete(coordinate)
        db.session.commit()

    except Exception:
        db.session.rollback()

        return jsonify({
            "error": "Failed to delete coordinate",
        }), 500

    return jsonify({
        "message": "Coordinate deleted successfully",
        "id": coordinate_id,
    }), 200