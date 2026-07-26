"""รวม import ทุก model เพื่อให้ Base.metadata เห็นครบ (สำคัญต่อ alembic autogenerate)."""

from app.models.poster import Poster, PosterImage
from app.models.reservation import Reservation
from app.models.user import OAuthIdentity, RefreshToken, User

__all__ = [
    "User",
    "RefreshToken",
    "OAuthIdentity",
    "Poster",
    "PosterImage",
    "Reservation",
]
