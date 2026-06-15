"""
Scénarios utilisateurs pour les tests fonctionnels Simeis.

Chaque scénario décrit les étapes, le résultat attendu, puis vérifie
automatiquement ces invariants via le SDK Python.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from sdk_loader import SimeisSDK

Scenario = Callable[[SimeisSDK], None]

# Argent de départ standard (voir simeis-data/src/player.rs INIT_MONEY).
INIT_MONEY = 72_000.0
# Préfixe activant le bonus testing (x10000) côté serveur.
RICH_PLAYER_PREFIX = "test-rich-"


@dataclass(frozen=True)
class ScenarioStep:
    action: str
    expected: str


@dataclass(frozen=True)
class UserScenario:
    name: str
    mechanic: str
    steps: tuple[ScenarioStep, ...]
    run: Scenario


def _log_step(index: int, action: str, expected: str) -> None:
    print(f"  [{index}] {action}")
    print(f"      attendu: {expected}")


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


def _buy_ship_with_pilot(sdk: SimeisSDK, station_id: int) -> tuple[dict, int]:
    ships = sdk.shop_list_ship(station_id)
    assert ships, "Le chantier naval doit proposer au moins un vaisseau"
    ship = sdk.buy_ship(station_id, ships[0]["id"])
    ship_id = ship["id"]

    pilot = sdk.hire_crew(station_id, "pilot")
    sdk.assign_crew_to_ship(station_id, ship_id, pilot["id"], "pilot")
    return ship, ship_id


def scenario_economy_new_player_buy_ship_and_miner(sdk: SimeisSDK) -> None:
    """
    Mécanique: économie / transactions station.
    """
    _log_step(
        1,
        "Créer un nouveau joueur",
        f"Argent de départ = {INIT_MONEY} (x10000 en mode testing)",
    )
    status = sdk.get_player_status()
    money_after_create = status["money"]
    assert money_after_create >= INIT_MONEY
    assert status["ships"] == []

    station_id = status["stations"][0]

    _log_step(2, "Acheter un vaisseau", "Transaction réussie et argent diminué")
    ships = sdk.shop_list_ship(station_id)
    ship_price = ships[0]["price"]
    bought = sdk.buy_ship(station_id, ships[0]["id"])
    assert "id" in bought

    status = sdk.get_player_status()
    money_after_ship = status["money"]
    assert len(status["ships"]) == 1
    assert money_after_ship < money_after_create
    assert abs((money_after_create - money_after_ship) - ship_price) < 1.0

    ship_id = status["ships"][0]["id"]

    _log_step(
        3, "Acheter un module Miner", "Transaction réussie et argent encore diminué"
    )
    money_before_module = status["money"]
    module = sdk.buy_module_on_ship(station_id, ship_id, "Miner")
    assert "id" in module

    status = sdk.get_player_status()
    money_after_module = status["money"]
    assert money_after_module < money_before_module

    ship = sdk.get_ship_status(ship_id)
    module_types = [m["modtype"] for m in ship.get("modules", {}).values()]
    assert "Miner" in module_types


def scenario_navigation_travel_to_planet(sdk: SimeisSDK) -> None:
    """
    Mécanique: navigation / vol de vaisseau.
    """
    status = sdk.get_player_status()
    station_id = status["stations"][0]
    station = sdk.get_station_status(station_id)

    _log_step(
        1, "Préparer un vaisseau avec pilote", "Vaisseau achetable et pilote assigné"
    )
    _, ship_id = _buy_ship_with_pilot(sdk, station_id)

    destination = _travel_destination(sdk, station_id, station)
    _log_step(
        2,
        f"Calculer le coût de trajet vers {destination}",
        "Durée de vol strictement positive",
    )
    costs = sdk.compute_travel_cost(ship_id, destination)
    assert costs["duration"] > 0.0

    _log_step(
        3, "Lancer le vol et attendre l'arrivée", "Vaisseau Idle à la destination"
    )
    _travel_with_ticks(sdk, ship_id, destination)
    ship = sdk.get_ship_status(ship_id)
    assert sdk._state_name(ship["state"]) == "Idle"
    assert tuple(ship["position"]) == destination


def scenario_market_read_prices_and_scan(sdk: SimeisSDK) -> None:
    """
    Mécanique: marché / exploration (scan de planètes).
    """
    status = sdk.get_player_status()
    station_id = status["stations"][0]

    _log_step(1, "Lire les prix du marché global", "Liste de ressources avec prix > 0")
    prices = sdk.get_market_prices()
    assert isinstance(prices, dict)
    assert len(prices) > 0
    assert all(price > 0.0 for price in prices.values())

    _log_step(
        2, "Scanner les planètes autour de la station", "Réponse de scan exploitable"
    )
    planets = sdk.scan_planets(station_id)
    assert isinstance(planets, list)

    _log_step(3, "Lire l'état de la station", "Station accessible avec cargo")
    station = sdk.get_station_status(station_id)
    assert station["id"] == station_id
    assert "cargo" in station


USER_SCENARIOS: tuple[UserScenario, ...] = (
    UserScenario(
        name="economy_new_player_buy_ship_and_miner",
        mechanic="économie / transactions",
        steps=(
            ScenarioStep(
                "Créer un nouveau joueur", f"Argent de départ >= {INIT_MONEY}"
            ),
            ScenarioStep("Acheter un vaisseau", "Transaction OK, argent diminué"),
            ScenarioStep(
                "Acheter un module Miner", "Transaction OK, argent encore diminué"
            ),
        ),
        run=scenario_economy_new_player_buy_ship_and_miner,
    ),
    UserScenario(
        name="navigation_travel_to_planet",
        mechanic="navigation / vol",
        steps=(
            ScenarioStep("Préparer vaisseau + pilote", "Vaisseau prêt au départ"),
            ScenarioStep("Calculer un trajet", "Durée > 0"),
            ScenarioStep("Effectuer le vol", "Vaisseau Idle à destination"),
        ),
        run=scenario_navigation_travel_to_planet,
    ),
    UserScenario(
        name="market_read_prices_and_scan",
        mechanic="marché / exploration",
        steps=(
            ScenarioStep("Lire les prix du marché", "Prix positifs disponibles"),
            ScenarioStep("Scanner les planètes", "Liste retournée par l'API"),
            ScenarioStep("Consulter la station", "Station et cargo accessibles"),
        ),
        run=scenario_market_read_prices_and_scan,
    ),
)


def unique_username(prefix: str = RICH_PLAYER_PREFIX) -> str:
    return f"{prefix}{int(time.time() * 1000)}"
