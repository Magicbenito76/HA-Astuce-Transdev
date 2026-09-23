"""Récupération et parsing des flux GTFS-RT temps réel du réseau Astuce."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import aiohttp
from google.transit import gtfs_realtime_pb2

_LOGGER = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=20)


async def async_fetch_bytes(session: aiohttp.ClientSession, url: str) -> bytes:
    async with session.get(url, timeout=_TIMEOUT) as resp:
        resp.raise_for_status()
        return await resp.read()


@dataclass
class StopTimeUpdate:
    stop_id: str
    arrival_time: int | None  # epoch UTC
    departure_time: int | None  # epoch UTC
    arrival_delay: int | None
    departure_delay: int | None
    schedule_relationship: int


@dataclass
class TripUpdate:
    trip_id: str
    route_id: str | None
    stop_time_updates: list[StopTimeUpdate] = field(default_factory=list)


@dataclass
class Alert:
    alert_id: str
    header: str
    description: str
    cause: int
    effect: int
    route_ids: set[str] = field(default_factory=set)
    stop_ids: set[str] = field(default_factory=set)
    network_wide: bool = False


def parse_trip_updates(raw: bytes) -> list[TripUpdate]:
    """Parse un flux GTFS-RT FeedMessage ne contenant que des TripUpdate."""
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(raw)

    updates: list[TripUpdate] = []
    for entity in feed.entity:
        if not entity.HasField("trip_update"):
            continue
        tu = entity.trip_update
        trip_update = TripUpdate(
            trip_id=tu.trip.trip_id,
            route_id=tu.trip.route_id or None,
        )
        for stu in tu.stop_time_update:
            arrival = stu.arrival.time if stu.HasField("arrival") else None
            departure = stu.departure.time if stu.HasField("departure") else None
            arrival_delay = (
                stu.arrival.delay if stu.HasField("arrival") and stu.arrival.HasField("delay") else None
            )
            departure_delay = (
                stu.departure.delay
                if stu.HasField("departure") and stu.departure.HasField("delay")
                else None
            )
            trip_update.stop_time_updates.append(
                StopTimeUpdate(
                    stop_id=stu.stop_id,
                    arrival_time=arrival or None,
                    departure_time=departure or None,
                    arrival_delay=arrival_delay,
                    departure_delay=departure_delay,
                    schedule_relationship=stu.schedule_relationship,
                )
            )
        updates.append(trip_update)
    return updates


def parse_alerts(raw: bytes) -> list[Alert]:
    """Parse un flux GTFS-RT FeedMessage ne contenant que des Alert."""
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(raw)

    alerts: list[Alert] = []
    for entity in feed.entity:
        if not entity.HasField("alert"):
            continue
        a = entity.alert
        header = _translated_text(a.header_text)
        description = _translated_text(a.description_text)
        alert = Alert(
            alert_id=entity.id,
            header=header,
            description=description,
            cause=a.cause,
            effect=a.effect,
        )
        if not a.informed_entity:
            alert.network_wide = True
        for informed in a.informed_entity:
            if informed.route_id:
                alert.route_ids.add(informed.route_id)
            if informed.stop_id:
                alert.stop_ids.add(informed.stop_id)
            if not informed.route_id and not informed.stop_id:
                alert.network_wide = True
        alerts.append(alert)
    return alerts


def _translated_text(translated_string) -> str:
    if not translated_string or not translated_string.translation:
        return ""
    for t in translated_string.translation:
        if t.language in ("fr", ""):
            return t.text
    return translated_string.translation[0].text
