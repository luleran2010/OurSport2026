import threading
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import BaseModel

from app.core.ids import id_timestamp_ms, new_id
from app.core.time import FrozenClock, UtcDatetime, ensure_utc, isoformat_z, parse_iso


def test_new_id_is_uuid_version_7_with_rfc_variant() -> None:
    value = new_id()

    assert value.version == 7
    assert value.variant == "specified in RFC 4122"


def test_new_ids_are_strictly_increasing() -> None:
    ids = [new_id() for _ in range(20_000)]

    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)


def test_new_ids_are_unique_across_threads() -> None:
    results: list[list[object]] = [[] for _ in range(8)]

    def worker(bucket: list[object]) -> None:
        bucket.extend(new_id() for _ in range(2_000))

    threads = [threading.Thread(target=worker, args=(bucket,)) for bucket in results]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    flat = [value for bucket in results for value in bucket]
    assert len(set(flat)) == len(flat)


def test_new_id_embeds_current_time() -> None:
    before = int(datetime.now(UTC).timestamp() * 1000)
    value = new_id()
    after = int(datetime.now(UTC).timestamp() * 1000)

    assert before <= id_timestamp_ms(value) <= after + 1


def test_new_id_with_explicit_time() -> None:
    at = datetime(2026, 10, 24, 14, 3, 11, 250_000, tzinfo=UTC)

    assert id_timestamp_ms(new_id(at)) == int(at.timestamp() * 1000)


def test_ensure_utc_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="naive"):
        ensure_utc(datetime(2026, 10, 24, 12, 0))


def test_ensure_utc_converts_offsets() -> None:
    helsinki_summer = timezone(timedelta(hours=3))

    result = ensure_utc(datetime(2026, 6, 1, 15, 0, tzinfo=helsinki_summer))

    assert result == datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    assert result.tzinfo is UTC


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (datetime(2026, 10, 24, 14, 3, 11, tzinfo=UTC), "2026-10-24T14:03:11Z"),
        (datetime(2026, 10, 24, 14, 3, 11, 250_000, tzinfo=UTC), "2026-10-24T14:03:11.250Z"),
        (
            datetime(2026, 10, 24, 20, 3, 11, tzinfo=timezone(timedelta(hours=6))),
            "2026-10-24T14:03:11Z",
        ),
    ],
)
def test_isoformat_z(value: datetime, expected: str) -> None:
    assert isoformat_z(value) == expected


def test_parse_iso_accepts_z_and_rejects_naive() -> None:
    assert parse_iso("2026-10-24T14:03:11Z") == datetime(2026, 10, 24, 14, 3, 11, tzinfo=UTC)
    with pytest.raises(ValueError):
        parse_iso("2026-10-24T14:03:11")


def test_frozen_clock_moves_only_when_told() -> None:
    clock = FrozenClock(datetime(2026, 10, 24, 9, 0, tzinfo=UTC))

    clock.advance(timedelta(minutes=20))
    assert clock.now() == datetime(2026, 10, 24, 9, 20, tzinfo=UTC)

    clock.set(datetime(2026, 10, 26, 18, 0, tzinfo=UTC))
    assert clock.now() == datetime(2026, 10, 26, 18, 0, tzinfo=UTC)


class _Event(BaseModel):
    at: UtcDatetime


def test_utc_datetime_field_validates_and_serialises_with_z() -> None:
    event = _Event.model_validate({"at": "2026-10-24T17:03:11+03:00"})

    assert event.at == datetime(2026, 10, 24, 14, 3, 11, tzinfo=UTC)
    assert event.model_dump(mode="json") == {"at": "2026-10-24T14:03:11Z"}
    with pytest.raises(ValueError):
        _Event.model_validate({"at": "2026-10-24T14:03:11"})
