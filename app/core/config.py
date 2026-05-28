from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Face Attendance API"
    environment: str = "development"
    debug: bool = False
    cors_origins: str = "*"

    database_url: str = "sqlite:///./attendance.db"

    # API runtime
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_workers: int = 1

    # Security
    secret_key: str = "change-this-secret-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    admin_username: str = "admin"
    admin_password: str = "admin123"

    # Face recognition
    face_tolerance: float = 0.5
    max_upload_mb: int = 5

    # Geofence bonus feature
    office_latitude: float = 37.7749
    office_longitude: float = -122.4194
    geofence_radius_meters: int = 300

    # Duplicate attendance prevention
    attendance_cooldown_minutes: int = 10

    # Admin/API pagination
    admin_default_limit: int = 50
    admin_max_limit: int = 500

    # Face matching scale controls
    face_hash_bits: int = 16
    face_candidate_limit: int = 5000
    max_full_scan_faces: int = 5000

    # Payments
    payment_provider: str = "demo"
    payment_currency: str = "usd"
    public_base_url: str = "http://127.0.0.1:8000"
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
