"""Security utilities module."""

from itsdangerous import URLSafeSerializer
from itsdangerous import URLSafeTimedSerializer

from app.core.config import settings

crypto_serializer = URLSafeSerializer(settings.SECRET_KEY)
crypto_timestamp_serializer = URLSafeTimedSerializer(settings.SECRET_KEY)
