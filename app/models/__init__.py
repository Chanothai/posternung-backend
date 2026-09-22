"""รวม import ทุก model เพื่อให้ Base.metadata เห็นครบ (สำคัญต่อ alembic autogenerate)."""

from app.models.engagement import Favorite, Review
from app.models.order import (
    Address,
    Order,
    OrderShippingDetail,
    OrderStatusHistory,
)
from app.models.payment import Dispute, Payment, Payout
from app.models.platform import NotificationOutbox, PlatformSetting
from app.models.poster import Poster, PosterImage
from app.models.poster_attribute_review import PosterAttributeReview
from app.models.poster_split import PosterSplit
from app.models.reservation import Reservation
from app.models.seller import SellerProfile
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
    # --- ADR-0028 marketplace (INF-32) ---
    "SellerProfile",
    "Address",
    "Order",
    "OrderShippingDetail",
    "OrderStatusHistory",
    "Payment",
    "Dispute",
    "Payout",
    "Review",
    "Favorite",
    "PlatformSetting",
    "NotificationOutbox",
]
