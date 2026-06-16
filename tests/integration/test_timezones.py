"""
Integration tests: timezone correctness.

Spain (Europe/Madrid) DST 2026:
  - Winter UTC+1 (CET)  → until 2026-03-29T01:00Z
  - Summer UTC+2 (CEST) → from  2026-03-29T01:00Z

Stats service filters by UTC start_at. Tests verify that events submitted with
explicit UTC offsets land in the correct month bucket.
"""
import pytest
from httpx import AsyncClient

from tests.conftest import _captured_tokens

SIGNUP_URL = "/auth/signup"
VERIFY_URL = "/auth/verify"
LOGIN_URL = "/auth/login"
EVENTS_URL = "/events"
STATS_URL = "/stats/monthly"


def _user(email: str, tz: str = "UTC") -> dict:
    return {"email": email, "password": "Tz123456!", "full_name": "TZ User", "timezone": tz}


async def _auth(client: AsyncClient, email: str = "tz@example.com", tz: str = "UTC") -> dict:
    r = await client.post(SIGNUP_URL, json=_user(email, tz))
    assert r.status_code == 202
    token = _captured_tokens.get(email)
    assert token
    await client.get(f"{VERIFY_URL}?token={token}")
    lr = await client.post(LOGIN_URL, json={"email": email, "password": "Tz123456!"})
    assert lr.status_code == 200
    return {"Authorization": f"Bearer {lr.json()['access_token']}"}


def _ev(start: str, end: str, title: str = "E", layer: str = "work") -> dict:
    return {"title": title, "start_at": start, "end_at": end, "layer": layer}


async def _create(client: AsyncClient, h: dict, start: str, end: str, title: str = "E") -> dict:
    r = await client.post(EVENTS_URL, json=_ev(start, end, title), headers=h)
    assert r.status_code == 201
    return r.json()


# ── Event storage with explicit UTC offsets ───────────────────────────────────


@pytest.mark.asyncio
async def test_event_with_positive_offset_accepted(client: AsyncClient) -> None:
    """Event submitted with +02:00 offset must be stored and retrievable."""
    h = await _auth(client, "tz_pos@example.com", "Europe/Madrid")
    # 2026-05-10T11:00:00+02:00 = 2026-05-10T09:00:00Z
    r = await client.post(
        EVENTS_URL,
        json=_ev("2026-05-10T11:00:00+02:00", "2026-05-10T12:00:00+02:00", "Madrid Summer"),
        headers=h,
    )
    assert r.status_code == 201
    data = r.json()
    assert "2026-05-10" in data["start_at"]


@pytest.mark.asyncio
async def test_event_with_negative_offset_accepted(client: AsyncClient) -> None:
    """Event submitted with -05:00 offset (Bogotá) must be stored correctly."""
    h = await _auth(client, "tz_neg@example.com", "America/Bogota")
    # 2026-05-10T04:00:00-05:00 = 2026-05-10T09:00:00Z
    r = await client.post(
        EVENTS_URL,
        json=_ev("2026-05-10T04:00:00-05:00", "2026-05-10T05:00:00-05:00", "Bogota"),
        headers=h,
    )
    assert r.status_code == 201


# ── Stats month filtering based on UTC start_at ───────────────────────────────


@pytest.mark.asyncio
async def test_event_late_may_madrid_summer_counted_in_may(client: AsyncClient) -> None:
    """
    2026-05-31T22:00:00+02:00 = 2026-05-31T20:00:00Z → May in UTC → May stats.
    """
    h = await _auth(client)
    await _create(client, h, "2026-05-31T22:00:00+02:00", "2026-05-31T23:00:00+02:00", "Late May CEST")
    data = (await client.get(f"{STATS_URL}?year=2026&month=5", headers=h)).json()
    assert data["total_events"] == 1


@pytest.mark.asyncio
async def test_event_at_utc_june_midnight_not_in_may(client: AsyncClient) -> None:
    """
    2026-06-01T00:00:00Z → June in UTC → must NOT appear in May stats.
    """
    h = await _auth(client, "tz2@example.com")
    await _create(client, h, "2026-06-01T00:00:00Z", "2026-06-01T01:00:00Z", "June UTC")
    data = (await client.get(f"{STATS_URL}?year=2026&month=5", headers=h)).json()
    assert data["total_events"] == 0


@pytest.mark.asyncio
async def test_event_on_may31_utc_evening_counted_in_may(client: AsyncClient) -> None:
    """
    2026-05-31T22:00:00Z is before the June boundary in UTC → must count in May stats.
    (This is equivalent to 2026-06-01T00:00:00+02:00 in Madrid summer time —
    the key insight: stats filter by UTC start_at, not local clock time.)
    """
    h = await _auth(client, "tz3@example.com")
    await _create(client, h, "2026-05-31T22:00:00Z", "2026-05-31T23:00:00Z", "May UTC Evening")
    data = (await client.get(f"{STATS_URL}?year=2026&month=5", headers=h)).json()
    assert data["total_events"] == 1


# ── DST boundary: Spain 2026-03-29T01:00Z clocks spring forward ──────────────


@pytest.mark.asyncio
async def test_events_across_dst_boundary_counted_in_correct_months(client: AsyncClient) -> None:
    """
    Before DST: 2026-03-28T10:00:00+01:00 = 2026-03-28T09:00:00Z → March
    After  DST: 2026-04-02T10:00:00+02:00 = 2026-04-02T08:00:00Z → April
    """
    h = await _auth(client, "dst@example.com")
    await _create(client, h, "2026-03-28T10:00:00+01:00", "2026-03-28T11:00:00+01:00", "Before DST")
    await _create(client, h, "2026-04-02T10:00:00+02:00", "2026-04-02T11:00:00+02:00", "After DST")

    march = (await client.get(f"{STATS_URL}?year=2026&month=3", headers=h)).json()
    april = (await client.get(f"{STATS_URL}?year=2026&month=4", headers=h)).json()
    assert march["total_events"] == 1
    assert april["total_events"] == 1


@pytest.mark.asyncio
async def test_event_at_dst_transition_hour_counted_in_march(client: AsyncClient) -> None:
    """
    Spain skips from 02:00→03:00 CET→CEST on 2026-03-29.
    2026-03-29T01:30:00+01:00 = 2026-03-29T00:30:00Z → March stats.
    """
    h = await _auth(client, "dst2@example.com")
    await _create(client, h, "2026-03-29T01:30:00+01:00", "2026-03-29T02:00:00+01:00", "DST Edge")
    data = (await client.get(f"{STATS_URL}?year=2026&month=3", headers=h)).json()
    assert data["total_events"] == 1


@pytest.mark.asyncio
async def test_event_just_after_dst_transition_counted_in_march(client: AsyncClient) -> None:
    """
    2026-03-29T03:30:00+02:00 = 2026-03-29T01:30:00Z → still in March.
    """
    h = await _auth(client, "dst3@example.com")
    await _create(client, h, "2026-03-29T03:30:00+02:00", "2026-03-29T04:00:00+02:00", "Post-DST March")
    data = (await client.get(f"{STATS_URL}?year=2026&month=3", headers=h)).json()
    assert data["total_events"] == 1


# ── Date range filter with TZ-aware params ────────────────────────────────────


@pytest.mark.asyncio
async def test_event_filter_with_tz_offset_in_start_end_params(client: AsyncClient) -> None:
    """GET /events with %2B00:00 (URL-encoded +00:00) filters correctly."""
    h = await _auth(client, "range@example.com")
    await _create(client, h, "2026-05-10T09:00:00Z", "2026-05-10T10:00:00Z", "In range")
    await _create(client, h, "2026-06-10T09:00:00Z", "2026-06-10T10:00:00Z", "Out of range")

    r = await client.get(
        f"{EVENTS_URL}?start=2026-05-01T00:00:00%2B00:00&end=2026-05-31T23:59:59%2B00:00",
        headers=h,
    )
    assert r.status_code == 200
    titles = [e["title"] for e in r.json()]
    assert "In range" in titles
    assert "Out of range" not in titles


@pytest.mark.asyncio
async def test_event_filter_with_negative_offset_params(client: AsyncClient) -> None:
    """Filter using -05:00 offset params (equivalent to UTC+5h ahead)."""
    h = await _auth(client, "range2@example.com")
    # 2026-05-10T09:00:00Z → in range of May 9 end to May 31 in -05:00 perspective
    await _create(client, h, "2026-05-10T09:00:00Z", "2026-05-10T10:00:00Z", "UTC event")

    # Filter: start=2026-05-01T00:00:00-05:00 = 2026-05-01T05:00:00Z
    #         end=2026-05-31T23:59:59-05:00 = 2026-06-01T04:59:59Z
    r = await client.get(
        f"{EVENTS_URL}?start=2026-05-01T00:00:00-05:00&end=2026-05-31T23:59:59-05:00",
        headers=h,
    )
    assert r.status_code == 200
    assert len(r.json()) == 1


# ── User timezone field has no impact on event UTC storage ────────────────────


@pytest.mark.asyncio
async def test_same_event_utc_stored_identically_regardless_of_user_timezone(
    client: AsyncClient,
) -> None:
    """Two users with different timezones creating the same UTC event get the same start_at."""
    h_utc = await _auth(client, "utc_user@example.com", "UTC")
    h_mad = await _auth(client, "mad_user@example.com", "Europe/Madrid")

    ev_utc = await _create(client, h_utc, "2026-05-10T09:00:00Z", "2026-05-10T10:00:00Z", "UTC")
    ev_mad = await _create(client, h_mad, "2026-05-10T09:00:00Z", "2026-05-10T10:00:00Z", "Madrid")

    # Both events were submitted with the same UTC timestamp — start_at must match
    # (the stored format may differ in TZ suffix but the point-in-time is identical)
    from datetime import datetime, timezone as _tz

    def _parse(dt_str: str) -> datetime:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00")).astimezone(_tz.utc)

    assert _parse(ev_utc["start_at"]) == _parse(ev_mad["start_at"])
