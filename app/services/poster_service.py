"""Business logic F2 Poster Catalog."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import PosterNotFound
from app.core.media import build_media_url
from app.models.poster import Poster
from app.repositories import poster_repository
from app.schemas.poster import (
    PaginatedPosterList,
    PosterDetailResponse,
    PosterFilterParams,
    PosterImageResponse,
    PosterListItem,
)


def _primary_image_url(poster: Poster) -> str | None:
    for image in poster.images:
        if image.is_primary:
            return build_media_url(image.storage_key)
    return None


def _to_list_item(poster: Poster) -> PosterListItem:
    return PosterListItem(
        id=poster.id,
        title=poster.title,
        price=poster.price,
        status=poster.status,
        condition_grade=poster.condition_grade,
        era_decade=poster.era_decade,
        studio=poster.studio,
        primary_image_url=_primary_image_url(poster),
    )


async def list_posters(
    session: AsyncSession, filters: PosterFilterParams
) -> PaginatedPosterList:
    posters, total = await poster_repository.list_with_filters(
        session,
        era_decade=filters.era_decade,
        condition_grade=filters.condition_grade,
        min_price=filters.min_price,
        max_price=filters.max_price,
        in_stock_only=filters.in_stock_only,
        limit=filters.limit,
        offset=filters.offset,
    )
    return PaginatedPosterList(
        items=[_to_list_item(poster) for poster in posters],
        total=total,
        limit=filters.limit,
        offset=filters.offset,
    )


async def get_poster_detail(
    session: AsyncSession, poster_id: uuid.UUID
) -> PosterDetailResponse:
    poster = await poster_repository.get_by_id(session, poster_id)
    if poster is None:
        raise PosterNotFound()

    return PosterDetailResponse(
        id=poster.id,
        title=poster.title,
        price=poster.price,
        status=poster.status,
        condition_grade=poster.condition_grade,
        era_decade=poster.era_decade,
        studio=poster.studio,
        primary_image_url=_primary_image_url(poster),
        tmdb_id=poster.tmdb_id,
        size=poster.size,
        description=poster.description,
        is_authenticated=poster.is_authenticated,
        authenticity_note=poster.authenticity_note,
        provenance=poster.provenance,
        images=[
            PosterImageResponse(
                id=image.id,
                url=build_media_url(image.storage_key),
                is_primary=image.is_primary,
                sort_order=image.sort_order,
            )
            for image in poster.images
        ],
        created_at=poster.created_at,
    )
