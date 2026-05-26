from __future__ import annotations

import time
from typing import Callable

from sdk_loader import SimeisSDK

Scenario = Callable[[SimeisSDK], None]


def _travel_with_ticks(
    sdk: SimeisSDK, ship_id: int, destination: tuple[int, int, int]
) -> dict:
    x, y, z = destination
    costs = sdk.post(f"/ship/{ship_id}/navigate/{x}/{y}/{z}")
    sdk.wait_until_ship_idle(ship_id, ts=0.05, max_wait=120)
    return costs


def _travel_destination(
    sdk: SimeisSDK, station_id: int, station: dict
) -> tuple[int, int, int]:
    planets = sdk.scan_planets(station_id)
    if planets:
        pos = planets[0]["position"]
        return tuple(pos)

    x, y, z = station["position"]
    return (x + 1, y, z)


def smoke_ping_and_version(sdk: SimeisSDK) -> None:
    assert sdk.api("/ping")["ping"] == "pong"
    version = sdk.get("/version")
    assert "version" in version
    assert isinstance(version["version"], str)
    assert version["version"]


def new_player_has_station_and_money(sdk: SimeisSDK) -> None:
    status = sdk.get_player_status()
    assert status["money"] > 0.0
    assert len(status["stations"]) >= 1
    assert status["ships"] == []


def market_and_station_are_readable(sdk: SimeisSDK) -> None:
    status = sdk.get_player_status()
    station_id = status["stations"][0]

    prices = sdk.get_market_prices()
    assert isinstance(prices, dict)
    assert len(prices) > 0

    station = sdk.get_station_status(station_id)
    assert station["id"] == station_id
    assert "position" in station
    assert "cargo" in station


def tick_endpoint_advances_game(sdk: SimeisSDK) -> None:
    sdk.post("/tick")
    sdk.post("/tick/3")


def buy_cheapest_ship(sdk: SimeisSDK) -> None:
    status = sdk.get_player_status()
    station_id = status["stations"][0]

    ships = sdk.shop_list_ship(station_id)
    assert ships, "Shipyard should list at least one ship"

    bought = sdk.buy_ship(station_id, ships[0]["id"])
    assert "id" in bought

    status = sdk.get_player_status()
    assert len(status["ships"]) >= 1


def hire_pilot_and_compute_travel(sdk: SimeisSDK) -> None:
    status = sdk.get_player_status()
    station_id = status["stations"][0]
    station = sdk.get_station_status(station_id)

    ships = sdk.shop_list_ship(station_id)
    ship = sdk.buy_ship(station_id, ships[0]["id"])
    ship_id = ship["id"]

    pilot = sdk.hire_crew(station_id, "pilot")
    sdk.assign_crew_to_ship(station_id, ship_id, pilot["id"], "pilot")

    destination = _travel_destination(sdk, station_id, station)
    costs = sdk.compute_travel_cost(ship_id, destination)
    assert costs["duration"] > 0.0


def scan_planets_from_station(sdk: SimeisSDK) -> None:
    status = sdk.get_player_status()
    station_id = status["stations"][0]

    planets = sdk.scan_planets(station_id)
    assert isinstance(planets, list)


def short_travel_with_ticks(sdk: SimeisSDK) -> None:
    status = sdk.get_player_status()
    station_id = status["stations"][0]
    station = sdk.get_station_status(station_id)

    ships = sdk.shop_list_ship(station_id)
    ship = sdk.buy_ship(station_id, ships[0]["id"])
    ship_id = ship["id"]

    pilot = sdk.hire_crew(station_id, "pilot")
    sdk.assign_crew_to_ship(station_id, ship_id, pilot["id"], "pilot")

    destination = _travel_destination(sdk, station_id, station)
    _travel_with_ticks(sdk, ship_id, destination)

    ship = sdk.get_ship_status(ship_id)
    assert sdk._state_name(ship["state"]) == "Idle"
    assert tuple(ship["position"]) == destination

    _travel_with_ticks(sdk, ship_id, tuple(station["position"]))
    ship = sdk.get_ship_status(ship_id)
    assert tuple(ship["position"]) == tuple(station["position"])


SCENARIOS: list[tuple[str, Scenario]] = [
    ("smoke_ping_and_version", smoke_ping_and_version),
    ("new_player_has_station_and_money", new_player_has_station_and_money),
    ("market_and_station_are_readable", market_and_station_are_readable),
    ("tick_endpoint_advances_game", tick_endpoint_advances_game),
    ("buy_cheapest_ship", buy_cheapest_ship),
    ("hire_pilot_and_compute_travel", hire_pilot_and_compute_travel),
    ("scan_planets_from_station", scan_planets_from_station),
    ("short_travel_with_ticks", short_travel_with_ticks),
]


def unique_username(prefix: str = "test-rich-ft") -> str:
    return f"{prefix}{int(time.time() * 1000)}"
