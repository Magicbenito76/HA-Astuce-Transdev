"""Coordinator : interroge le temps réel Transdev Rouen et les alertes."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
import homeassistant.util.dt as dt_util

from .const import (
    ALERTS_MIN_INTERVAL,
    GTFS_RT_ALERTS_URL,
    GTFS_RT_TRIPUPDATES_URL,
    MAX_DEPARTURES,
    SOURCE_ESTIMATED,
    SOURCE_REALTIME,
    SOURCE_SCHEDULED,
    UPDATE_INTERVAL_RT,
)
from .gtfs_rt import Alert, async_fetch_bytes, parse_alerts, parse_trip_updates
from .gtfs_static import GtfsStatic

_LOGGER = logging.getLogger(__name__)


def _local_naive_to_utc(naive_dt: datetime) -> datetime:
    """Convertit un datetime naïf en heure locale HA en datetime UTC aware."""
    local_tz = dt_util.DEFAULT_TIME_ZONE
    localize = getattr(local_tz, "localize", None)
    aware = localize(naive_dt) if localize else naive_dt.replace(tzinfo=local_tz)
    return dt_util.as_utc(aware)


class AstuceRouenCoordinator(DataUpdateCoordinator[None]):
    """Rafraîchit le temps réel toutes les 30s et les alertes toutes les 60s."""

    def __init__(self, hass: HomeAssistant, gtfs: GtfsStatic) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="astuce_rouen_transdev",
            update_interval=UPDATE_INTERVAL_RT,
        )
        self.gtfs = gtfs
        self.alerts: list[Alert] = []
        self.realtime_by_stop: dict[str, list[dict]] = {}
        self.route_delays: dict[str, int] = {}
        self._last_alerts_fetch: datetime | None = None

    async def _async_update_data(self) -> None:
        session = async_get_clientsession(self.hass)

        try:
            raw = await async_fetch_bytes(session, GTFS_RT_TRIPUPDATES_URL)
            trip_updates = parse_trip_updates(raw)
            self._rebuild_realtime_index(trip_updates)
        except Exception as err:  # noqa: BLE001 - on garde les dernières données connues
            _LOGGER.warning("Temps réel Transdev Rouen indisponible : %s", err)

        now = dt_util.utcnow()
        if (
            self._last_alerts_fetch is None
            or now - self._last_alerts_fetch >= ALERTS_MIN_INTERVAL
        ):
            try:
                raw = await async_fetch_bytes(session, GTFS_RT_ALERTS_URL)
                self.alerts = parse_alerts(raw)
                self._last_alerts_fetch = now
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Alertes trafic Astuce indisponibles : %s", err)

        return None

    # ------------------------------------------------------------------

    def _rebuild_realtime_index(self, trip_updates) -> None:
        by_stop: dict[str, list[dict]] = {}
        route_delays: dict[str, int] = {}

        for tu in trip_updates:
            trip_info = self.gtfs.trips.get(tu.trip_id)
            route_id = tu.route_id or (trip_info["route_id"] if trip_info else None)
            if route_id is None or route_id not in self.gtfs.routes:
                continue
            headsign = trip_info["headsign"] if trip_info else None

            for stu in tu.stop_time_updates:
                epoch = stu.departure_time or stu.arrival_time
                if epoch is None:
                    continue
                delay = stu.departure_delay or stu.arrival_delay or 0
                route_delays[route_id] = delay
                by_stop.setdefault(stu.stop_id, []).append(
                    {
                        "trip_id": tu.trip_id,
                        "route_id": route_id,
                        "headsign": headsign,
                        "time": dt_util.utc_from_timestamp(epoch),
                        "delay": delay,
                        "source": SOURCE_REALTIME,
                    }
                )

        for entries in by_stop.values():
            entries.sort(key=lambda e: e["time"])

        self.realtime_by_stop = by_stop
        self.route_delays = route_delays

    # ------------------------------------------------------------------
    # API utilisée par les entités
    # ------------------------------------------------------------------

    def get_departures(
        self, stop_id: str, route_id: str, headsign: str, limit: int = MAX_DEPARTURES
    ) -> list[dict]:
        now_utc = dt_util.utcnow()
        now_local = dt_util.now().replace(tzinfo=None)

        realtime = [
            e
            for e in self.realtime_by_stop.get(stop_id, [])
            if e["route_id"] == route_id
            and (headsign is None or e["headsign"] == headsign)
            and e["time"] >= now_utc
        ]
        results = list(realtime[:limit])
        known_trip_ids = {e["trip_id"] for e in realtime}

        if len(results) < limit:
            delay = self.route_delays.get(route_id, 0)
            scheduled = self.gtfs.get_scheduled_departures(
                stop_id, route_id, headsign, after=now_local, limit=limit + len(known_trip_ids) + 5
            )
            for dep in scheduled:
                if dep.trip_id in known_trip_ids:
                    continue
                adj_time_local = dep.time + timedelta(seconds=delay) if delay else dep.time
                adj_time_utc = _local_naive_to_utc(adj_time_local)
                if adj_time_utc < now_utc:
                    continue
                results.append(
                    {
                        "trip_id": dep.trip_id,
                        "route_id": route_id,
                        "headsign": dep.headsign,
                        "time": adj_time_utc,
                        "delay": delay,
                        "source": SOURCE_ESTIMATED if delay else SOURCE_SCHEDULED,
                    }
                )
                if len(results) >= limit:
                    break

        results.sort(key=lambda e: e["time"])
        return results[:limit]

    def get_alert_messages(self, stop_id: str, route_id: str) -> list[dict]:
        matching = [
            a
            for a in self.alerts
            if a.network_wide or route_id in a.route_ids or stop_id in a.stop_ids
        ]
        return [
            {
                "title": a.alert_id,
                "message": a.header or a.description,
                "full_message": (a.header + " — " + a.description).strip(" —")
                if a.description and a.header
                else (a.header or a.description),
            }
            for a in matching
        ]
