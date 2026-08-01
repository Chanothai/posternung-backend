"""Unit test ของ poster_service — ครอบ filter/pagination logic + not-found."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import PosterNotFound
from app.core.media import build_media_url
from app.models.enums import PosterCondition, PosterStatus
from app.models.poster import Poster, PosterImage
from app.schemas.poster import PosterFilterParams
from app.services import poster_service


async def _make_poster(
    session: AsyncSession,
    *,
    title: str,
    price: str,
    status: PosterStatus = PosterStatus.available,
    condition_grade: PosterCondition | None = None,
    era_decade: int | None = None,
    with_primary_image: bool = False,
) -> Poster:
    poster = Poster(
        title=title,
        price=Decimal(price),
        status=status,
        condition_grade=condition_grade,
        era_decade=era_decade,
    )
    session.add(poster)
    await session.flush()

    if with_primary_image:
        session.add(
            PosterImage(
                poster_id=poster.id,
                storage_key=f"posters/public/{poster.id}/01-test.jpg",
                is_primary=True,
            )
        )
        await session.flush()
        await session.refresh(poster, attribute_names=["images"])

    return poster


async def test_list_posters_filters_by_era_decade(db_session: AsyncSession) -> None:
    await _make_poster(db_session, title="Poster 1980s", price="100", era_decade=1980)
    await _make_poster(db_session, title="Poster 1990s", price="100", era_decade=1990)

    result = await poster_service.list_posters(
        db_session, PosterFilterParams(era_decade=1980)
    )

    assert result.total == 1
    assert result.items[0].title == "Poster 1980s"


async def test_list_posters_filters_by_price_range(db_session: AsyncSession) -> None:
    await _make_poster(db_session, title="Cheap", price="50")
    await _make_poster(db_session, title="Mid", price="150")
    await _make_poster(db_session, title="Expensive", price="500")

    result = await poster_service.list_posters(
        db_session,
        PosterFilterParams(min_price=Decimal("100"), max_price=Decimal("200")),
    )

    assert result.total == 1
    assert result.items[0].title == "Mid"


async def test_list_posters_in_stock_only(db_session: AsyncSession) -> None:
    await _make_poster(db_session, title="Available", price="100")
    await _make_poster(
        db_session, title="Reserved", price="100", status=PosterStatus.reserved
    )
    await _make_poster(db_session, title="Sold", price="100", status=PosterStatus.sold)

    result = await poster_service.list_posters(
        db_session, PosterFilterParams(in_stock_only=True)
    )

    assert result.total == 1
    assert result.items[0].title == "Available"


async def test_list_posters_pagination_total_independent_of_limit(
    db_session: AsyncSession,
) -> None:
    for i in range(5):
        await _make_poster(db_session, title=f"Poster {i}", price="100")

    result = await poster_service.list_posters(
        db_session, PosterFilterParams(limit=2, offset=0)
    )

    assert result.total == 5
    assert len(result.items) == 2
    assert result.limit == 2
    assert result.offset == 0


async def test_list_posters_primary_image_url(db_session: AsyncSession) -> None:
    poster = await _make_poster(
        db_session, title="With Image", price="100", with_primary_image=True
    )

    result = await poster_service.list_posters(db_session, PosterFilterParams())

    item = next(i for i in result.items if i.id == poster.id)
    assert item.primary_image_url is not None
    assert item.primary_image_url == build_media_url(
        f"posters/public/{poster.id}/01-test.jpg"
    )


async def test_get_poster_detail_not_found_raises(db_session: AsyncSession) -> None:
    with pytest.raises(PosterNotFound) as exc_info:
        await poster_service.get_poster_detail(db_session, uuid.uuid4())

    assert exc_info.value.status_code == 404
    assert exc_info.value.error_code == "POSTER_NOT_FOUND"


async def test_get_poster_detail_includes_images(db_session: AsyncSession) -> None:
    poster = await _make_poster(
        db_session, title="Detail Poster", price="250", with_primary_image=True
    )

    detail = await poster_service.get_poster_detail(db_session, poster.id)

    assert detail.id == poster.id
    assert len(detail.images) == 1
    assert detail.images[0].is_primary is True
