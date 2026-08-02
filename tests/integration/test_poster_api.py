"""Integration tests (HTTP-level) ของ F2 poster catalog."""

import uuid
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.media import build_media_url
from app.models.poster import Poster, PosterImage

API = "/api/v1/posters"


def _storage_key(poster_id) -> str:
    return f"posters/public/{poster_id}/01-test.jpg"


async def _seed_poster(
    session: AsyncSession, *, title: str = "Test Poster", price: str = "100"
) -> Poster:
    poster = Poster(title=title, price=Decimal(price))
    session.add(poster)
    await session.flush()
    session.add(
        PosterImage(
            poster_id=poster.id,
            storage_key=_storage_key(poster.id),
            is_primary=True,
        )
    )
    await session.commit()
    return poster


async def test_list_posters_empty_returns_200_with_empty_items(
    client: AsyncClient,
) -> None:
    res = await client.get(API)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["items"] == []
    assert body["total"] == 0


async def test_list_posters_returns_seeded_poster(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    poster = await _seed_poster(db_session, title="Seeded Poster")

    res = await client.get(API)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "Seeded Poster"
    assert body["items"][0]["primary_image_url"] == build_media_url(
        _storage_key(poster.id)
    )


async def test_list_posters_limit_zero_is_422(client: AsyncClient) -> None:
    res = await client.get(API, params={"limit": 0})
    assert res.status_code == 422
    assert res.json()["error_code"] == "VALIDATION_ERROR"


async def test_list_posters_limit_over_100_is_422(client: AsyncClient) -> None:
    res = await client.get(API, params={"limit": 101})
    assert res.status_code == 422


async def test_list_posters_negative_min_price_is_422(client: AsyncClient) -> None:
    res = await client.get(API, params={"min_price": -1})
    assert res.status_code == 422


async def test_get_poster_detail_returns_images(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    poster = await _seed_poster(db_session, title="Detail Poster")

    res = await client.get(f"{API}/{poster.id}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["title"] == "Detail Poster"
    assert len(body["images"]) == 1
    assert body["images"][0]["is_primary"] is True
    assert body["images"][0]["url"] == build_media_url(_storage_key(poster.id))


async def test_get_poster_detail_not_found_404(client: AsyncClient) -> None:
    res = await client.get(f"{API}/{uuid.uuid4()}")
    assert res.status_code == 404
    assert res.json()["error_code"] == "POSTER_NOT_FOUND"


async def test_get_poster_detail_invalid_uuid_422(client: AsyncClient) -> None:
    res = await client.get(f"{API}/not-a-uuid")
    assert res.status_code == 422


# --- visibility filtering (ADR-0006 D2/D5 — G6) ---


async def _seed_poster_with_images(
    session: AsyncSession, *, title: str, images: list[tuple[str, bool, int]]
) -> Poster:
    """images = [(storage_key_suffix, is_primary, sort_order), ...]

    suffix ถูกต่อท้าย `posters/` ตรง ๆ เพื่อให้ระบุ visibility segment ได้ในเทส
    """
    poster = Poster(title=title, price=Decimal("100"))
    session.add(poster)
    await session.flush()
    for suffix, is_primary, sort_order in images:
        session.add(
            PosterImage(
                poster_id=poster.id,
                storage_key=f"posters/{suffix.format(poster_id=poster.id)}",
                is_primary=is_primary,
                sort_order=sort_order,
            )
        )
    await session.commit()
    return poster


async def test_list_posters_with_internal_image_returns_200_not_500(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    poster = await _seed_poster_with_images(
        db_session,
        title="Internal Primary",
        images=[
            ("internal/{poster_id}/01-uv.jpg", True, 0),
            ("public/{poster_id}/02-front.jpg", False, 1),
        ],
    )

    res = await client.get(API)

    assert res.status_code == 200, res.text
    item = next(i for i in res.json()["items"] if i["id"] == str(poster.id))
    assert item["primary_image_url"] is None


async def test_get_poster_detail_filters_internal_images(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    poster = await _seed_poster_with_images(
        db_session,
        title="Mixed Images",
        images=[
            ("public/{poster_id}/01-front.jpg", True, 0),
            ("internal/{poster_id}/02-uv.jpg", False, 1),
            ("public/{poster_id}/03-back.jpg", False, 2),
        ],
    )

    res = await client.get(f"{API}/{poster.id}")

    assert res.status_code == 200, res.text
    body = res.json()
    assert [image["url"] for image in body["images"]] == [
        build_media_url(f"posters/public/{poster.id}/01-front.jpg"),
        build_media_url(f"posters/public/{poster.id}/03-back.jpg"),
    ]
    assert body["primary_image_url"] == build_media_url(
        f"posters/public/{poster.id}/01-front.jpg"
    )


async def test_get_poster_detail_all_internal_images_returns_200_empty_images(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    poster = await _seed_poster_with_images(
        db_session,
        title="All Internal",
        images=[
            ("internal/{poster_id}/01-uv.jpg", True, 0),
            ("internal/{poster_id}/02-raking.jpg", False, 1),
        ],
    )

    res = await client.get(f"{API}/{poster.id}")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["images"] == []
    assert body["primary_image_url"] is None


async def test_get_poster_detail_without_images_returns_200(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    poster = await _seed_poster_with_images(db_session, title="No Images", images=[])

    res = await client.get(f"{API}/{poster.id}")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["images"] == []
    assert body["primary_image_url"] is None
