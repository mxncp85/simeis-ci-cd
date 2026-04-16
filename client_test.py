import sys
import time

from sdk import SimeisError, SimeisSDK


RESOURCE_MIN_RANK = {
    "Carbon": 0,
    "Hydrogen": 0,
    "Iron": 2,
    "Oxygen": 2,
    "Copper": 4,
    "Helium": 4,
    "Gold": 6,
    "Ozone": 6,
}

RESOURCE_DIFFICULTY = {
    "Carbon": 0.25,
    "Hydrogen": 0.25,
    "Iron": 0.9375,
    "Oxygen": 0.9375,
    "Copper": 2.75,
    "Helium": 2.75,
    "Gold": 3.5,
    "Ozone": 3.5,
}

FAMILY_RESOURCES = {
    "solid": ("Carbon", "Iron", "Copper", "Gold"),
    "gas": ("Hydrogen", "Oxygen", "Helium", "Ozone"),
}

MODULE_BY_FAMILY = {
    "solid": "Miner",
    "gas": "GasSucker",
}

MODULE_FAMILY = {
    "Miner": "solid",
    "GasSucker": "gas",
}


class Game:
    def __init__(self, username, ip, port, verbose=False):
        self.sdk = SimeisSDK(username, ip, port)
        self.verbose = verbose

    def _log_action(self, message):
        print(f"[ACTION] {message}")

    def _log_verbose(self, message):
        if self.verbose:
            print(f"[VERBOSE] {message}")

    def _log_ship_state(self, ship, prefix="Ship"):
        if not self.verbose:
            return

        cargo = ship.get("cargo", {})
        resources = cargo.get("resources", {})
        non_zero = {k: round(v, 3) for k, v in resources.items() if v > 0}
        self._log_verbose(
            (
                f"{prefix} {ship['id']} | state={ship.get('state')} | pos={ship.get('position')} | "
                f"fuel={round(ship.get('fuel_tank', 0.0), 2)}/{round(ship.get('fuel_tank_capacity', 0.0), 2)} | "
                f"hull_decay={round(ship.get('hull_decay', 0.0), 2)}/{round(ship.get('hull_resistance', 0.0), 2)} | "
                f"cargo={round(cargo.get('usage', 0.0), 2)}/{round(cargo.get('capacity', 0.0), 2)} | "
                f"resources={non_zero}"
            )
        )

    def _mapping_value(self, mapping, key, default=None):
        if key in mapping:
            return mapping[key]
        skey = str(key)
        if skey in mapping:
            return mapping[skey]
        return default

    def _family_for_module(self, modtype):
        return MODULE_FAMILY.get(modtype)

    def _family_for_planet(self, planet):
        return "solid" if planet["solid"] else "gas"

    def _extraction_rate(self, resource, module_rank, operator_rank):
        min_rank = RESOURCE_MIN_RANK[resource]
        if operator_rank <= min_rank:
            return 0.0

        rank = (operator_rank - min_rank) * module_rank
        difficulty = RESOURCE_DIFFICULTY[resource] ** 2.5
        return 6.25 * ((rank / difficulty) ** 0.6)

    def _family_score(self, ship, family, market_prices):
        crew = ship.get("crew", {})
        score = 0.0

        for module in ship.get("modules", {}).values():
            if self._family_for_module(module["modtype"]) != family:
                continue

            operator_id = module.get("operator")
            if operator_id is None:
                continue

            operator = self._mapping_value(crew, operator_id)
            if operator is None:
                continue

            operator_rank = operator["rank"]
            module_rank = module["rank"]
            for resource in FAMILY_RESOURCES[family]:
                rate = self._extraction_rate(resource, module_rank, operator_rank)
                if rate > 0.0:
                    score += rate * market_prices.get(resource, 0.0)

        return score

    def _best_family_for_ship(self, ship, market_prices):
        solid_score = self._family_score(ship, "solid", market_prices)
        gas_score = self._family_score(ship, "gas", market_prices)

        if solid_score == 0.0 and gas_score == 0.0:
            return "solid" if market_prices.get("Carbon", 0.0) >= market_prices.get("Hydrogen", 0.0) else "gas"
        return "solid" if solid_score >= gas_score else "gas"

    def _best_planet_for_family(self, planets, family):
        for planet in planets:
            if self._family_for_planet(planet) == family:
                return planet
        return planets[0] if planets else None

    def _best_ship(self, ships, market_prices):
        def ship_key(ship):
            score = max(
                self._family_score(ship, "solid", market_prices),
                self._family_score(ship, "gas", market_prices),
            )
            cargo_cap = ship.get("cargo", {}).get("capacity", 0.0)
            return (score, cargo_cap)

        return max(ships, key=ship_key)

    def _reserve(self, status):
        return max(5000.0, float(status.get("costs", 0.0)) * 120.0)

    def _upgrade_crew_price(self, crew_member):
        wage = {
            "Operator": 0.75,
            "Pilot": 0.75 * 8.0,
            "Trader": 0.75 * 5.0,
            "Soldier": 0.75 * 2.5,
        }[crew_member["member_type"]]
        return (wage ** 1.75) * 1900.0

    def _module_type(self, family):
        return MODULE_BY_FAMILY[family]

    def _buy_module_and_operator(self, station_id, ship_id, family):
        self._log_action(f"Buying {self._module_type(family)} module for ship {ship_id}")
        module = self.sdk.buy_module_on_ship(station_id, ship_id, self._module_type(family))
        self._log_action(f"Hiring operator for module {module['id']}")
        operator = self.sdk.hire_crew(station_id, "operator")
        self._log_action(f"Assigning operator {operator['id']} to module {module['id']} on ship {ship_id}")
        self.sdk.assign_crew_to_ship(station_id, ship_id, operator["id"], module["id"])

    def _ensure_ship_idle(self, ship_id):
        ship = self.sdk.get_ship_status(ship_id)
        self._log_ship_state(ship, "Before idle-check")
        state = ship.get("state")
        if state == "Idle":
            return ship

        if state == "Extracting":
            self._log_action(f"Ship {ship_id} is extracting, stopping extraction")
            try:
                self.sdk.post(f"/ship/{ship_id}/extraction/stop")
            except SimeisError:
                pass
        elif state == "InFlight":
            self._log_action(f"Ship {ship_id} is in flight, stopping navigation")
            try:
                self.sdk.post(f"/ship/{ship_id}/navigation/stop")
            except SimeisError:
                pass

        self._log_action(f"Waiting for ship {ship_id} to become idle")
        self.sdk.wait_until_ship_idle(ship_id)
        ship = self.sdk.get_ship_status(ship_id)
        self._log_ship_state(ship, "After idle-check")
        return ship

    def _safe_travel(self, ship_id, destination):
        try:
            self.sdk.travel(ship_id, destination)
            return
        except SimeisError as err:
            if "already occupied" not in str(err).lower():
                raise

        self._log_action(f"Ship {ship_id} busy, recovering before retry")
        self._ensure_ship_idle(ship_id)
        self.sdk.travel(ship_id, destination)

    def _ensure_ship_setup(self, station_id, ship, family):
        ship_id = ship["id"]

        if not ship.get("pilot"):
            self._log_action(f"No pilot on ship {ship_id}, hiring one")
            pilot = self.sdk.hire_crew(station_id, "pilot")
            self._log_action(f"Assigning pilot {pilot['id']} to ship {ship_id}")
            self.sdk.assign_crew_to_ship(station_id, ship_id, pilot["id"], "pilot")

        if not self.sdk.station_has_trader(station_id):
            self._log_action(f"No trader on station {station_id}, hiring one")
            trader = self.sdk.hire_crew(station_id, "trader")
            self._log_action(f"Assigning trader {trader['id']} to station {station_id}")
            self.sdk.assign_trader_to_station(station_id, trader["id"])

        ship = self.sdk.get_ship_status(ship_id)
        matching_modules = []
        for mod_id, module in ship.get("modules", {}).items():
            if self._family_for_module(module["modtype"]) == family:
                matching_modules.append((mod_id, module))

        if not matching_modules:
            self._log_action(f"Ship {ship_id} has no {family} module, buying one")
            self._buy_module_and_operator(station_id, ship_id, family)
            ship = self.sdk.get_ship_status(ship_id)
            self._log_ship_state(ship, "Growth loop")
            matching_modules = []
            for mod_id, module in ship.get("modules", {}).items():
                if self._family_for_module(module["modtype"]) == family:
                    matching_modules.append((mod_id, module))

        for mod_id, module in matching_modules:
            if module.get("operator") is None:
                self._log_action(f"Module {mod_id} has no operator, hiring one")
                operator = self.sdk.hire_crew(station_id, "operator")
                self._log_action(f"Assigning operator {operator['id']} to module {mod_id}")
                self.sdk.assign_crew_to_ship(station_id, ship_id, operator["id"], mod_id)

        return self.sdk.get_ship_status(ship_id)

    def _grow_ship(self, station_id, ship_id, family):
        while True:
            status = self.sdk.get_player_status()
            reserve = self._reserve(status)
            ship = self.sdk.get_ship_status(ship_id)

            if status["money"] <= reserve + 4500.0:
                self._log_action(
                    f"Stop growing ship {ship_id}: money {round(status['money'], 2)} <= reserve {round(reserve, 2)} + module cost"
                )
                break

            self._log_action(f"Growing ship {ship_id}: adding a new {family} module")
            self._buy_module_and_operator(station_id, ship_id, family)
            ship = self.sdk.get_ship_status(ship_id)

            upgraded_any = False
            for mod_id, module in ship.get("modules", {}).items():
                if self._family_for_module(module["modtype"]) != family:
                    continue
                operator_id = module.get("operator")
                if operator_id is None:
                    continue
                operator = self._mapping_value(ship.get("crew", {}), operator_id)
                if operator is None:
                    continue
                price = self._upgrade_crew_price(operator)
                if self.sdk.get_player_status()["money"] > reserve + price:
                    self._log_action(
                        f"Upgrading operator {operator_id} on ship {ship_id} (estimated price {round(price, 2)})"
                    )
                    self.sdk.post(f"/station/{station_id}/crew/upgrade/ship/{ship_id}/{operator_id}")
                    upgraded_any = True
                    break

            if upgraded_any:
                continue

    def gameloop(self):
        status = self.sdk.get_player_status()
        station_id = status["stations"][0]
        planets = self.sdk.scan_planets(station_id)
        market_prices = self.sdk.get_market_prices()

        if len(status["ships"]) == 0:
            family = "solid" if market_prices.get("Carbon", 0.0) >= market_prices.get("Hydrogen", 0.0) else "gas"
            if not any(self._family_for_planet(planet) == family for planet in planets):
                family = "gas" if family == "solid" else "solid"

            self._log_action(f"New game detected. Starting strategy with {family} extraction")
            self._log_action("Buying first ship")
            shipyard = self.sdk.shop_list_ship(station_id)
            ship = shipyard[0]
            self._log_action(
                f"Selected ship {ship['id']} (price {round(ship['price'], 2)}, cargo {ship['cargo_capacity']})"
            )
            bought_ship = self.sdk.buy_ship(station_id, ship["id"])
            ship_id = bought_ship.get("id", ship["id"])

            self._buy_module_and_operator(station_id, ship_id, family)
            ship = self.sdk.get_ship_status(ship_id)
            ship = self._ensure_ship_setup(station_id, ship, family)
            self._grow_ship(station_id, ship_id, family)
        else:
            ship = self._best_ship(status["ships"], market_prices)
            ship_id = ship["id"]
            family = self._best_family_for_ship(ship, market_prices)
            self._log_action(f"Existing game detected. Reusing ship {ship_id} with {family} strategy")
            self._log_action(f"Returning ship {ship_id} to station {station_id} and unloading")
            self.sdk.return_station_and_unload_all(station_id, ship_id)
            ship = self._ensure_ship_setup(station_id, ship, family)
            self._grow_ship(station_id, ship_id, family)

        while True:
            status = self.sdk.get_player_status()
            if status["money"] <= 0:
                print("You lost")
                return

            market_prices = self.sdk.get_market_prices()
            planets = self.sdk.scan_planets(station_id)
            ship = self.sdk.get_ship_status(ship_id)
            family = self._best_family_for_ship(ship, market_prices)
            planet = self._best_planet_for_family(planets, family)
            self._log_ship_state(ship, "Cycle start")

            if planet is None:
                print("No planet available to mine")
                return

            print(
                "Credits: {}, costs: {}, target: {} planet at {}".format(
                    round(status["money"], 2),
                    round(status["costs"], 2),
                    family,
                    planet["position"],
                )
            )

            self._ensure_ship_idle(ship_id)
            self._log_action(f"Traveling ship {ship_id} to {planet['position']}")
            self._safe_travel(ship_id, planet["position"])
            self._log_action(f"Starting extraction with ship {ship_id}")
            info = self.sdk.start_extraction(ship_id)

            stats = info["mining_rate"]
            totpersec = 0.0
            for res, amnt in stats.items():
                print(f"{res}: {amnt} /sec")
                totpersec += amnt * market_prices.get(res, 0.0)
            print(f"Gross: {totpersec:.2f} credits / sec")

            self._log_action(f"Waiting {round(info['time_fill_cargo'], 2)}s for cargo fill")
            time.sleep(info["time_fill_cargo"])
            self.sdk.wait_until_ship_idle(ship_id)

            self._log_action(f"Returning ship {ship_id} to station {station_id} and unloading")
            self.sdk.return_station_and_unload_all(station_id, ship_id)
            self._log_ship_state(self.sdk.get_ship_status(ship_id), "After unload")

            cycle_gain = 0.0
            for res, amnt in self.sdk.get_station_resources(station_id).items():
                if res in ["Fuel", "Hull"]:
                    continue
                if amnt <= 0.0:
                    continue
                got = self.sdk.sell_resource(station_id, res, amnt)
                cycle_gain += got["added_money"]
                print("Sold", amnt, "of", res, "for", got["added_money"], "credits")

            fuel = self.sdk.buy_fuel_for_refuel(station_id, ship_id)
            if fuel is not None:
                cycle_gain -= fuel["removed_money"]
                print("Bought fuel for", fuel["removed_money"], "credits")
            self._log_action(f"Refueling ship {ship_id}")
            self.sdk.refuel_ship(station_id, ship_id)

            hull = self.sdk.buy_hull_for_repair(station_id, ship_id)
            if hull is not None:
                cycle_gain -= hull["removed_money"]
                print("Bought hull for", hull["removed_money"], "credits")
            self._log_action(f"Repairing ship {ship_id}")
            self.sdk.repair_ship(station_id, ship_id)

            print("Cycle profit:", round(cycle_gain, 2))
            self._grow_ship(station_id, ship_id, family)
            print("")


if __name__ == "__main__":
    args = [arg for arg in sys.argv[1:] if arg != "--verbose"]
    verbose = "--verbose" in sys.argv[1:]

    if len(args) < 3:
        print("Usage: python3.py ./client.py <username> <IP> <port> [--verbose]")
        sys.exit(1)

    name = args[0]
    ip = args[1]
    port = int(args[2])
    game = Game(name, ip, port, verbose=verbose)
    game.gameloop()
