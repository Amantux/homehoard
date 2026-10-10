"""Timestamps leave the API as ISO-8601 with an explicit +00:00 offset."""
import re
from datetime import date, datetime, timedelta, timezone

from app.timeutil import as_utc, iso_utc, utcnow

ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:.]+\+00:00$")


def test_utcnow_is_aware_utc():
    assert utcnow().utcoffset() == timedelta(0)


def test_as_utc_none():
    assert as_utc(None) is None


def test_as_utc_naive_is_taken_as_utc():
    out = as_utc(datetime(2026, 1, 2, 3, 4, 5))
    assert out == datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert out.utcoffset() == timedelta(0)


def test_as_utc_aware_is_converted():
    plus2 = timezone(timedelta(hours=2))
    out = as_utc(datetime(2026, 1, 2, 5, 0, tzinfo=plus2))
    assert out == datetime(2026, 1, 2, 3, 0, tzinfo=timezone.utc)
    assert out.tzinfo == timezone.utc


def test_iso_utc_naive_and_aware_carry_offset():
    assert iso_utc(datetime(2026, 1, 2, 3, 4, 5)) == "2026-01-02T03:04:05+00:00"
    assert ISO_UTC.match(iso_utc(utcnow()))
    assert iso_utc(None) is None


def test_iso_utc_date_passthrough():
    assert iso_utc(date(2026, 1, 2)) == "2026-01-02"


def test_api_created_at_has_utc_offset(auth_client):
    item = auth_client.post("/api/v1/items", json={"name": "Clock"}).get_json()
    assert ISO_UTC.match(item["createdAt"]), item["createdAt"]
    again = auth_client.get(f"/api/v1/items/{item['id']}").get_json()
    assert ISO_UTC.match(again["createdAt"]), again["createdAt"]
    assert ISO_UTC.match(again["updatedAt"]), again["updatedAt"]
