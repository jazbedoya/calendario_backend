"""
Integration tests: /stats/monthly — layer counts, hours, soft-delete exclusion,
busiest-days ordering, December/January boundary, user isolation.
"""
import pytest
from httpx import AsyncClient

SIGNUP_URL = "/auth/signup"
EVENTS_URL = "/events"
STATS_URL = "/stats/monthly"


def _user(email: str) -> dict:
    return {"email": email, "password": "Stats123!", "full_name": "Stats User", "timezone": "UTC"}


async def _auth(client: AsyncClient, email: str = "stats@example.com") -> dict:
    r = await client.post(SIGNUP_URL, json=_user(email))
    assert r.status_code == 201
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _ev(title: str, start: str, end: str, layer: str = "work") -> dict:
    return {"title": title, "start_at": start, "end_at": end, "layer": layer}


async def _create(client: AsyncClient, h: dict, title: str, start: str, end: str, layer: str = "work") -> dict:
    r = await client.post(EVENTS_URL, json=_ev(title, start, end, layer), headers=h)
    assert r.status_code == 201
    return r.json()


# ── Auth guard ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stats_requires_auth(client: AsyncClient) -> None:
    r = await client.get(f"{STATS_URL}?year=2026&month=5")
    assert r.status_code in (401, 403)


# ── Empty month ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stats_empty_month_returns_zeros(client: AsyncClient) -> None:
    h = await _auth(client)
    r = await client.get(f"{STATS_URL}?year=2026&month=5", headers=h)
    assert r.status_code == 200
    data = r.json()
    assert data["total_events"] == 0
    assert data["by_layer"] == []
    assert data["busiest_days"] == []
    assert data["year"] == 2026
    assert data["month"] == 5


# ── Single layer ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stats_counts_events_in_layer(client: AsyncClient) -> None:
    h = await _auth(client)
    for i in range(3):
        await _create(client, h, f"Work {i}", f"2026-05-{10+i:02d}T09:00:00Z", f"2026-05-{10+i:02d}T10:00:00Z")
    data = (await client.get(f"{STATS_URL}?year=2026&month=5", headers=h)).json()
    assert data["total_events"] == 3
    work = next(s for s in data["by_layer"] if s["layer"] == "work")
    assert work["count"] == 3


@pytest.mark.asyncio
async def test_stats_hours_calculation_exact(client: AsyncClient) -> None:
    h = await _auth(client)
    # 1.5-hour event
    await _create(client, h, "Long", "2026-05-10T08:00:00Z", "2026-05-10T09:30:00Z")
    data = (await client.get(f"{STATS_URL}?year=2026&month=5", headers=h)).json()
    work = next(s for s in data["by_layer"] if s["layer"] == "work")
    assert work["total_hours"] == 1.5


@pytest.mark.asyncio
async def test_stats_hours_multiple_events_sum(client: AsyncClient) -> None:
    h = await _auth(client)
    # Two 1-hour events = 2.0 total hours
    await _create(client, h, "A", "2026-05-10T08:00:00Z", "2026-05-10T09:00:00Z")
    await _create(client, h, "B", "2026-05-11T08:00:00Z", "2026-05-11T09:00:00Z")
    data = (await client.get(f"{STATS_URL}?year=2026&month=5", headers=h)).json()
    work = next(s for s in data["by_layer"] if s["layer"] == "work")
    assert work["total_hours"] == 2.0


# ── Multi-layer ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stats_multi_layer_breakdown(client: AsyncClient) -> None:
    h = await _auth(client)
    await _create(client, h, "F", "2026-05-01T09:00:00Z", "2026-05-01T10:00:00Z", "family")
    await _create(client, h, "W1", "2026-05-02T09:00:00Z", "2026-05-02T10:00:00Z", "work")
    await _create(client, h, "W2", "2026-05-03T09:00:00Z", "2026-05-03T10:00:00Z", "work")
    await _create(client, h, "P", "2026-05-04T09:00:00Z", "2026-05-04T10:00:00Z", "personal")

    data = (await client.get(f"{STATS_URL}?year=2026&month=5", headers=h)).json()
    layers = {s["layer"]: s["count"] for s in data["by_layer"]}
    assert layers["family"] == 1
    assert layers["work"] == 2
    assert layers["personal"] == 1
    assert data["total_events"] == 4


# ── Soft delete ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stats_excludes_soft_deleted_events(client: AsyncClient) -> None:
    h = await _auth(client)
    ev = await _create(client, h, "To Delete", "2026-05-10T09:00:00Z", "2026-05-10T10:00:00Z")
    await client.delete(f"{EVENTS_URL}/{ev['id']}", headers=h)

    data = (await client.get(f"{STATS_URL}?year=2026&month=5", headers=h)).json()
    assert data["total_events"] == 0


@pytest.mark.asyncio
async def test_stats_restored_event_is_counted(client: AsyncClient) -> None:
    h = await _auth(client)
    ev = await _create(client, h, "Restore Me", "2026-05-10T09:00:00Z", "2026-05-10T10:00:00Z")
    await client.delete(f"{EVENTS_URL}/{ev['id']}", headers=h)
    await client.post(f"{EVENTS_URL}/{ev['id']}/restore", headers=h)

    data = (await client.get(f"{STATS_URL}?year=2026&month=5", headers=h)).json()
    assert data["total_events"] == 1


# ── Busiest days ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stats_busiest_days_ordered_by_count_desc(client: AsyncClient) -> None:
    h = await _auth(client)
    # Day 10: 3 events — Day 15: 1 event
    for i in range(3):
        await _create(client, h, f"E{i}", f"2026-05-10T{9+i:02d}:00:00Z", f"2026-05-10T{10+i:02d}:00:00Z")
    await _create(client, h, "Solo", "2026-05-15T09:00:00Z", "2026-05-15T10:00:00Z")

    days = (await client.get(f"{STATS_URL}?year=2026&month=5", headers=h)).json()["busiest_days"]
    assert days[0]["date"] == "2026-05-10"
    assert days[0]["count"] == 3
    assert days[1]["date"] == "2026-05-15"
    assert days[1]["count"] == 1


@pytest.mark.asyncio
async def test_stats_busiest_days_capped_at_five(client: AsyncClient) -> None:
    h = await _auth(client)
    # Create events on 7 different days
    for d in range(1, 8):
        await _create(client, h, f"Day{d}", f"2026-05-{d:02d}T09:00:00Z", f"2026-05-{d:02d}T10:00:00Z")

    days = (await client.get(f"{STATS_URL}?year=2026&month=5", headers=h)).json()["busiest_days"]
    assert len(days) <= 5


# ── Month boundary ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stats_december_excludes_next_january(client: AsyncClient) -> None:
    h = await _auth(client)
    await _create(client, h, "Dec", "2026-12-15T09:00:00Z", "2026-12-15T10:00:00Z")
    await _create(client, h, "Jan", "2027-01-05T09:00:00Z", "2027-01-05T10:00:00Z")

    dec = (await client.get(f"{STATS_URL}?year=2026&month=12", headers=h)).json()
    assert dec["total_events"] == 1

    jan = (await client.get(f"{STATS_URL}?year=2027&month=1", headers=h)).json()
    assert jan["total_events"] == 1


@pytest.mark.asyncio
async def test_stats_event_at_exact_month_start_is_included(client: AsyncClient) -> None:
    h = await _auth(client)
    await _create(client, h, "Start", "2026-05-01T00:00:00Z", "2026-05-01T01:00:00Z")
    data = (await client.get(f"{STATS_URL}?year=2026&month=5", headers=h)).json()
    assert data["total_events"] == 1


@pytest.mark.asyncio
async def test_stats_event_at_last_second_of_month_is_included(client: AsyncClient) -> None:
    h = await _auth(client)
    # 2026-05-31T23:59:59Z — last second of May in UTC
    await _create(client, h, "LastSec", "2026-05-31T23:59:59Z", "2026-06-01T00:59:59Z")
    data = (await client.get(f"{STATS_URL}?year=2026&month=5", headers=h)).json()
    assert data["total_events"] == 1


@pytest.mark.asyncio
async def test_stats_event_starting_in_june_not_in_may(client: AsyncClient) -> None:
    h = await _auth(client)
    await _create(client, h, "June", "2026-06-01T00:00:00Z", "2026-06-01T01:00:00Z")
    data = (await client.get(f"{STATS_URL}?year=2026&month=5", headers=h)).json()
    assert data["total_events"] == 0


# ── User isolation ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stats_does_not_include_other_users_events(client: AsyncClient) -> None:
    h1 = await _auth(client, "s1@example.com")
    h2 = await _auth(client, "s2@example.com")
    await _create(client, h1, "S1 Event", "2026-05-10T09:00:00Z", "2026-05-10T10:00:00Z")
    data = (await client.get(f"{STATS_URL}?year=2026&month=5", headers=h2)).json()
    assert data["total_events"] == 0
