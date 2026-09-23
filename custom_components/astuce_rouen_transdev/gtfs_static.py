"""Gestion du GTFS statique (arrêts, lignes, horaires théoriques) Astuce.

Seules les lignes exploitées par Transdev Rouen sont conservées en mémoire,
comme le fait l'intégration TaM Montpellier avec le tramway.
"""
from __future__ import annotations

import csv
import io
import logging
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .const import (
    GTFS_STATIC_URL,
    STORAGE_KEY,
    STORAGE_VERSION,
    TRANSDEV_ROUTE_SHORT_NAMES,
)

_LOGGER = logging.getLogger(__name__)


def _parse_gtfs_time(value: str) -> int | None:
    """Convertit un horaire GTFS ('HH:MM:SS', peut dépasser 24h) en secondes."""
    if not value:
        return None
    try:
        h, m, s = value.strip().split(":")
        return int(h) * 3600 + int(m) * 60 + int(s)
    except (ValueError, AttributeError):
        return None


def _parse_gtfs_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y%m%d").date()
    except ValueError:
        return None


def _combine_day_seconds(day: date, seconds: int) -> datetime:
    """Combine une date et un nombre de secondes depuis minuit (GTFS)."""
    return datetime(day.year, day.month, day.day) + timedelta(seconds=seconds)


@dataclass
class ScheduledDeparture:
    """Un passage théorique à un arrêt donné."""

    trip_id: str
    route_id: str
    headsign: str
    time: datetime


@dataclass
class GtfsStatic:
    """Représentation en mémoire du GTFS statique filtré Transdev Rouen."""

    hass: HomeAssistant

    routes: dict = field(default_factory=dict)  # route_id -> info
    trips: dict = field(default_factory=dict)  # trip_id -> info
    stops: dict = field(default_factory=dict)  # stop_id -> info
    # stop_id -> list[(trip_id, departure_seconds, stop_sequence)]
    stop_times: dict = field(default_factory=dict)
    # route_id -> {headsign: set(trip_id)}
    directions_by_route: dict = field(default_factory=dict)
    calendar: dict = field(default_factory=dict)  # service_id -> info
    calendar_dates: dict = field(default_factory=dict)  # (service_id, date) -> type

    loaded: bool = False

    def __post_init__(self) -> None:
        self._store: Store = Store(self.hass, STORAGE_VERSION, STORAGE_KEY)

    # ------------------------------------------------------------------
    # Chargement / téléchargement
    # ------------------------------------------------------------------

    async def async_ensure_loaded(self) -> None:
        """Charge le cache disque si présent, sinon télécharge le GTFS."""
        if self.loaded:
            return
        cached = await self._store.async_load()
        if cached:
            self._restore_from_cache(cached)
            self.loaded = True
            _LOGGER.debug("GTFS Astuce chargé depuis le cache local")
            return
        await self.async_refresh()

    async def async_refresh(self) -> None:
        """Télécharge et parse le GTFS officiel Astuce, puis met en cache."""
        session = async_get_clientsession(self.hass)
        _LOGGER.debug("Téléchargement du GTFS Astuce (%s)", GTFS_STATIC_URL)
        async with session.get(GTFS_STATIC_URL, timeout=60) as resp:
            resp.raise_for_status()
            raw = await resp.read()

        data = await self.hass.async_add_executor_job(self._parse_zip, raw)
        (
            self.routes,
            self.trips,
            self.stops,
            self.stop_times,
            self.directions_by_route,
            self.calendar,
            self.calendar_dates,
        ) = data
        self.loaded = True
        await self._store.async_save(self._to_cache())
        _LOGGER.info(
            "GTFS Astuce mis à jour : %d lignes Transdev, %d arrêts, %d trajets",
            len(self.routes),
            len(self.stops),
            len(self.trips),
        )

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_zip(raw: bytes):
        """Parse le zip GTFS (exécuté hors boucle asyncio)."""
        with zipfile.ZipFile(io.BytesIO(raw)) as z:

            def read_csv(name: str):
                if name not in z.namelist():
                    return []
                with z.open(name) as f:
                    text = io.TextIOWrapper(f, encoding="utf-8-sig")
                    return list(csv.DictReader(text))

            routes_rows = read_csv("routes.txt")
            trips_rows = read_csv("trips.txt")
            stops_rows = read_csv("stops.txt")
            stop_times_rows = read_csv("stop_times.txt")
            calendar_rows = read_csv("calendar.txt")
            calendar_dates_rows = read_csv("calendar_dates.txt")

        # -- routes filtrées Transdev Rouen ---------------------------------
        routes: dict[str, dict] = {}
        for row in routes_rows:
            short_name = (row.get("route_short_name") or "").strip()
            if short_name not in TRANSDEV_ROUTE_SHORT_NAMES:
                continue
            route_id = row["route_id"]
            routes[route_id] = {
                "short_name": short_name,
                "long_name": (row.get("route_long_name") or "").strip(),
                "color": (row.get("route_color") or "").strip() or None,
                "text_color": (row.get("route_text_color") or "").strip() or None,
            }

        # -- trips appartenant à ces lignes ---------------------------------
        trips: dict[str, dict] = {}
        directions_by_route: dict[str, dict[str, set]] = {}
        for row in trips_rows:
            route_id = row.get("route_id")
            if route_id not in routes:
                continue
            trip_id = row["trip_id"]
            headsign = (row.get("trip_headsign") or "").strip() or routes[route_id][
                "long_name"
            ]
            trips[trip_id] = {
                "route_id": route_id,
                "service_id": row.get("service_id"),
                "headsign": headsign,
                "direction_id": row.get("direction_id"),
            }
            directions_by_route.setdefault(route_id, {}).setdefault(
                headsign, set()
            ).add(trip_id)

        # -- stop_times pour ces trips uniquement ---------------------------
        stop_times: dict[str, list[tuple[str, int, int]]] = {}
        used_stop_ids: set[str] = set()
        for row in stop_times_rows:
            trip_id = row.get("trip_id")
            if trip_id not in trips:
                continue
            stop_id = row["stop_id"]
            dep = _parse_gtfs_time(row.get("departure_time") or row.get("arrival_time"))
            if dep is None:
                continue
            try:
                seq = int(row.get("stop_sequence") or 0)
            except ValueError:
                seq = 0
            stop_times.setdefault(stop_id, []).append((trip_id, dep, seq))
            used_stop_ids.add(stop_id)

        for stop_id, entries in stop_times.items():
            entries.sort(key=lambda e: e[1])

        # -- arrêts utilisés uniquement --------------------------------------
        stops: dict[str, dict] = {}
        for row in stops_rows:
            stop_id = row.get("stop_id")
            if stop_id not in used_stop_ids:
                continue
            stops[stop_id] = {
                "name": (row.get("stop_name") or "").strip(),
                "lat": row.get("stop_lat"),
                "lon": row.get("stop_lon"),
            }

        # -- calendrier des services utilisés uniquement ----------------------
        used_service_ids = {t["service_id"] for t in trips.values()}
        calendar: dict[str, dict] = {}
        for row in calendar_rows:
            service_id = row.get("service_id")
            if service_id not in used_service_ids:
                continue
            days = {
                i
                for i, key in enumerate(
                    [
                        "monday",
                        "tuesday",
                        "wednesday",
                        "thursday",
                        "friday",
                        "saturday",
                        "sunday",
                    ]
                )
                if row.get(key) == "1"
            }
            calendar[service_id] = {
                "days": days,
                "start_date": row.get("start_date"),
                "end_date": row.get("end_date"),
            }

        calendar_dates: dict[str, dict[str, int]] = {}
        for row in calendar_dates_rows:
            service_id = row.get("service_id")
            if service_id not in used_service_ids:
                continue
            calendar_dates.setdefault(service_id, {})[row.get("date")] = int(
                row.get("exception_type") or 0
            )

        return routes, trips, stops, stop_times, directions_by_route, calendar, calendar_dates

    # ------------------------------------------------------------------
    # Cache disque (.storage)
    # ------------------------------------------------------------------

    def _to_cache(self) -> dict:
        return {
            "routes": self.routes,
            "trips": self.trips,
            "stops": self.stops,
            "stop_times": self.stop_times,
            "directions_by_route": {
                route_id: {hs: sorted(trip_ids) for hs, trip_ids in dirs.items()}
                for route_id, dirs in self.directions_by_route.items()
            },
            "calendar": self.calendar,
            "calendar_dates": self.calendar_dates,
        }

    def _restore_from_cache(self, cached: dict) -> None:
        self.routes = cached.get("routes", {})
        self.trips = cached.get("trips", {})
        self.stops = cached.get("stops", {})
        self.stop_times = {
            stop_id: [tuple(e) for e in entries]
            for stop_id, entries in cached.get("stop_times", {}).items()
        }
        self.directions_by_route = {
            route_id: {hs: set(trip_ids) for hs, trip_ids in dirs.items()}
            for route_id, dirs in cached.get("directions_by_route", {}).items()
        }
        self.calendar = cached.get("calendar", {})
        self.calendar_dates = cached.get("calendar_dates", {})

    # ------------------------------------------------------------------
    # API utilisée par le config_flow
    # ------------------------------------------------------------------

    def get_lines(self) -> list[tuple[str, str]]:
        """Retourne [(route_id, libellé)] trié par nom de ligne."""
        items = [
            (route_id, info["short_name"] or info["long_name"])
            for route_id, info in self.routes.items()
        ]
        return sorted(items, key=lambda i: i[1])

    def get_directions(self, route_id: str) -> list[str]:
        """Retourne la liste des destinations (headsigns) d'une ligne."""
        return sorted(self.directions_by_route.get(route_id, {}).keys())

    def get_stops_for_direction(self, route_id: str, headsign: str) -> list[tuple[str, str]]:
        """Retourne [(stop_id, nom)] desservis par une ligne/direction."""
        trip_ids = self.directions_by_route.get(route_id, {}).get(headsign, set())
        stop_ids: set[str] = set()
        for stop_id, entries in self.stop_times.items():
            if any(trip_id in trip_ids for trip_id, _, _ in entries):
                stop_ids.add(stop_id)
        result = [
            (stop_id, self.stops.get(stop_id, {}).get("name") or stop_id)
            for stop_id in stop_ids
        ]
        return sorted(result, key=lambda i: i[1])

    # ------------------------------------------------------------------
    # API utilisée par le coordinator / les capteurs
    # ------------------------------------------------------------------

    def is_service_active(self, service_id: str, day: date) -> bool:
        exception = self.calendar_dates.get(service_id, {}).get(day.strftime("%Y%m%d"))
        if exception == 1:
            return True
        if exception == 2:
            return False

        cal = self.calendar.get(service_id)
        if not cal:
            return False
        start = _parse_gtfs_date(cal.get("start_date") or "")
        end = _parse_gtfs_date(cal.get("end_date") or "")
        if start and day < start:
            return False
        if end and day > end:
            return False
        return day.weekday() in cal["days"]

    def get_scheduled_departures(
        self,
        stop_id: str,
        route_id: str,
        headsign: str,
        after: datetime,
        limit: int = 10,
    ) -> list[ScheduledDeparture]:
        """Prochains passages théoriques à un arrêt pour une ligne/direction.

        `after` doit être un datetime *naïf, heure locale*.
        """
        trip_ids = self.directions_by_route.get(route_id, {}).get(headsign, set())
        entries = self.stop_times.get(stop_id, [])
        results: list[ScheduledDeparture] = []

        # On regarde le service d'hier (passages après minuit, horaires GTFS
        # pouvant dépasser 24:00:00) et d'aujourd'hui.
        for day_offset in (-1, 0):
            day = after.date() + timedelta(days=day_offset)
            for trip_id, dep_seconds, _seq in entries:
                if trip_id not in trip_ids:
                    continue
                trip = self.trips.get(trip_id)
                if not trip or not self.is_service_active(trip["service_id"], day):
                    continue
                dep_dt = _combine_day_seconds(day, dep_seconds)
                if dep_dt < after:
                    continue
                results.append(
                    ScheduledDeparture(
                        trip_id=trip_id,
                        route_id=route_id,
                        headsign=headsign,
                        time=dep_dt,
                    )
                )

        results.sort(key=lambda d: d.time)
        return results[:limit]
