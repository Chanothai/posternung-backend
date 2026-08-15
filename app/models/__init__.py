"""รวม import ทุก model เพื่อให้ Base.metadata เห็นครบ (สำคัญต่อ alembic autogenerate)."""

from app.models.poster import Poster, PosterImage
from app.models.poster_attribute_review import PosterAttributeReview
from app.models.poster_split import PosterSplit
from app.models.reservation import Reservation
from app.models.user import OAuthIdentity, RefreshToken, User

__all__ = [
    "User",
    "RefreshToken",
    "OAuthIdentity",
    "Poster",
    "PosterImage",
    "PosterAttributeReview",
    "PosterSplit",
    "Reservation",
]
