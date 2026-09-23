"""Constantes pour l'intégration Astuce Rouen (lignes Transdev Rouen)."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "astuce_rouen_transdev"

# Point d'Accès National (transport.data.gouv.fr) - jeu de données
# "Réseau urbain Astuce" - Métropole Rouen Normandie
GTFS_STATIC_URL = (
    "https://api.mrn.cityway.fr/dataflow/offre-tc/download"
    "?provider=ASTUCE&dataFormat=gtfs&dataProfil=ASTUCE"
)
GTFS_RT_TRIPUPDATES_URL = (
    "https://api.mrn.cityway.fr/dataflow/horaire-tc-tr/download"
    "?provider=TCAR&dataFormat=gtfs-rt"
)
# Alertes : fichier "réseau entier", pas spécifique à un exploitant.
GTFS_RT_ALERTS_URL = (
    "https://api.mrn.cityway.fr/dataflow/info-transport/download"
    "?provider=ASTUCE&dataFormat=gtfs-rt"
)

# Lignes exploitées par Transdev Rouen (cf. description du jeu de données).
# Utilisé pour filtrer le GTFS statique (routes.txt / route_short_name) afin
# de ne garder que ce qui correspond au flux GTFS-RT Transdev.
TRANSDEV_ROUTE_SHORT_NAMES = frozenset(
    {
        "Metro", "T1", "T2", "T3", "T4",
        "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8",
        "Noctambus",
        "10", "11", "15", "20", "22", "27", "41", "43",
    }
)

CONF_STOPS = "stops"

CONF_STOP_UID = "uid"
CONF_STOP_ROUTE_ID = "route_id"
CONF_STOP_ROUTE_SHORT_NAME = "route_short_name"
CONF_STOP_ROUTE_COLOR = "route_color"
CONF_STOP_HEADSIGN = "headsign"
CONF_STOP_ID = "stop_id"
CONF_STOP_NAME = "stop_name"

UPDATE_INTERVAL_RT = timedelta(seconds=30)
ALERTS_MIN_INTERVAL = timedelta(seconds=60)

# Rafraîchissement du GTFS théorique, comme pour TaM Montpellier : au
# démarrage puis chaque nuit à 3h30.
STATIC_REFRESH_HOUR = 3
STATIC_REFRESH_MINUTE = 30

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_gtfs_static"

MAX_DEPARTURES = 6

ATTR_LINE = "line"
ATTR_LINE_COLOR = "line_color"
ATTR_DESTINATION = "destination"
ATTR_DELAY = "delay"
ATTR_SOURCE = "source"
ATTR_DEPARTURES = "departures"
ATTR_MESSAGE = "message"
ATTR_FULL_MESSAGE = "full_message"
ATTR_ALERTS = "alerts"

SOURCE_REALTIME = "realtime"
SOURCE_ESTIMATED = "estimated"
SOURCE_SCHEDULED = "scheduled"
