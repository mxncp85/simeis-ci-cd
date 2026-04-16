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

LOOP_DELAY_SEC = 0.08
RESERVE_SECONDS = 12.0
MIN_RESERVE = 900.0
MODULE_COST = 4500.0
EPS = 1e-6

OP_UPGRADE_MIN_BANK = 220000.0
MOBILITY_MIN_BANK = 28000.0
TRADE_MIN_BANK = 55000.0
TRADE_BUDGET_RATIO = 0.20
TRADE_TARGET_PROFIT = 1.16
TRADE_STOP_LOSS = 0.88
TRADE_MAX_HOLD = 180
TRADER_RECHECK_LOOPS = 24


class Game:
    def __init__(self, username, ip, port, verbose=False, max_ships=10):
        self.sdk = SimeisSDK(username, ip, port)
        self.verbose = verbose
        self.max_ships = max_ships
        self.last_station_id = None
        self._planets_cache = None   # planets are static – scan once
        self.price_history = {}
        self.trade_positions = {}
        self.loop_count = 0
        self.market_enabled = True
        self.trader_ready = False
        self.last_trader_check_loop = -TRADER_RECHECK_LOOPS
        self.improvement_counts = {
            "ships": 0,
            "modules": 0,
            "pilot_upgrades": 0,
            "operator_upgrades": 0,
            "cargo_upgrades": 0,
            "reactor_upgrades": 0,
            "trade_buys": 0,
        }

    def _log_action(self, message):
        print(f"[ACTION] {message}")

    def _log_verbose(self, message):
        if self.verbose:
            print(f"[VERBOSE] {message}")

    def _record_improvement(self, key, amount=1):
        self.improvement_counts[key] = self.improvement_counts.get(key, 0) + amount

    def _improvement_summary(self):
        return (
            f"upgrades ships={self.improvement_counts.get('ships', 0)} "
            f"modules={self.improvement_counts.get('modules', 0)} "
            f"pilot={self.improvement_counts.get('pilot_upgrades', 0)} "
            f"operator={self.improvement_counts.get('operator_upgrades', 0)} "
            f"cargo={self.improvement_counts.get('cargo_upgrades', 0)} "
            f"reactor={self.improvement_counts.get('reactor_upgrades', 0)} "
            f"trade={self.improvement_counts.get('trade_buys', 0)}"
        )

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

    def _state_name(self, state):
        if isinstance(state, str):
            return state
        if isinstance(state, dict) and len(state) == 1:
            return next(iter(state.keys()))
        return str(state)

    def _safe_tick(self):
        # Useful in testing mode where time progresses only on /tick.
        try:
            self.sdk.post("/tick")
        except Exception:
            pass

    def _record_prices(self, market_prices):
        for res, price in market_prices.items():
            if res in ("Fuel", "Hull"):
                continue
            hist = self.price_history.setdefault(res, [])
            hist.append(float(price))
            if len(hist) > 80:
                del hist[0]

    def _resource_price_ratio(self, resource, current_price):
        hist = self.price_history.get(resource, [])
        if len(hist) < 12:
            return 0.5
        low = min(hist)
        high = max(hist)
        span = high - low
        if span <= EPS:
            return 0.5
        return max(0.0, min(1.0, (float(current_price) - low) / span))

    def _is_no_trader_error(self, err):
        return "doesn't have a trader assigned" in str(err).lower()

    def _ensure_trader_for_market(self, station_id):
        if self.trader_ready and (self.loop_count - self.last_trader_check_loop) < TRADER_RECHECK_LOOPS:
            return True

        try:
            if self.sdk.station_has_trader(station_id):
                self.market_enabled = True
                self.trader_ready = True
                self.last_trader_check_loop = self.loop_count
                return True

            self._log_action(f"No trader on station {station_id}, hiring one for market access")
            trader = self.sdk.hire_crew(station_id, "trader")
            self.sdk.assign_trader_to_station(station_id, trader["id"])
            self.market_enabled = True
            self.trader_ready = True
            self.last_trader_check_loop = self.loop_count
            self._log_action(f"Trader {trader['id']} assigned to station {station_id}")
            return True
        except SimeisError as err:
            self.trader_ready = False
            self._log_verbose(f"Could not assign trader on station {station_id}: {err}")
            return False

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

    def _reserve(self, status):
        return max(MIN_RESERVE, float(status.get("costs", 0.0)) * RESERVE_SECONDS)

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

    def _default_family(self, market_prices, planets):
        """Always target the nearest planet – minimises travel time and hull damage."""
        if planets:
            return self._family_for_planet(planets[0])
        return "solid" if market_prices.get("Carbon", 0.0) >= market_prices.get("Hydrogen", 0.0) else "gas"

    def _best_planet_for_ship(self, ship, planets):
        """
        GasSucker works on ALL planet types (gas resources exist on solid planets too).
        So GasSucker-only ships always go to the nearest planet.
        Miner-only ships go to the nearest solid planet.
        Dual-module ships prefer nearest solid planet (double extraction).
        """
        if not planets:
            return None
        has_solid = self._ship_has_module_family(ship, "solid")
        has_gas = self._ship_has_module_family(ship, "gas")
        if has_solid and has_gas:
            for p in planets:                   # already sorted nearest-first
                if self._family_for_planet(p) == "solid":
                    return p
            return planets[0]
        if has_gas:
            return planets[0]                   # GasSucker → nearest planet of any type
        if has_solid:
            for p in planets:
                if self._family_for_planet(p) == "solid":
                    return p
            return None
        return planets[0]

    def _ship_has_module_family(self, ship, family):
        for module in ship.get("modules", {}).values():
            if self._family_for_module(module.get("modtype")) == family:
                return True
        return False

    def _buy_module_and_operator(self, station_id, ship_id, family):
        self._log_action(f"Buying {self._module_type(family)} module for ship {ship_id}")
        module = self.sdk.buy_module_on_ship(station_id, ship_id, self._module_type(family))
        self._log_action(f"Hiring operator for module {module['id']}")
        operator = self.sdk.hire_crew(station_id, "operator")
        self._log_action(f"Assigning operator {operator['id']} to module {module['id']} on ship {ship_id}")
        self.sdk.assign_crew_to_ship(station_id, ship_id, operator["id"], module["id"])

    def _safe_travel(self, ship_id, destination, wait_end=False):
        try:
            self.sdk.travel(ship_id, destination, wait_end=wait_end)
            return
        except SimeisError as err:
            if "already occupied" not in str(err).lower():
                raise
        self._log_action(f"Ship {ship_id} busy, recovering before retry")
        return

    def _ensure_ship_setup(self, station_id, ship, family, station_pos=None):
        ship_id = ship["id"]
        at_station = station_pos is None or ship.get("position") == station_pos

        if not at_station:
            # Ship/station endpoints for crew and modules require docking.
            return ship

        if not ship.get("pilot"):
            self._log_action(f"No pilot on ship {ship_id}, hiring one")
            pilot = self.sdk.hire_crew(station_id, "pilot")
            self._log_action(f"Assigning pilot {pilot['id']} to ship {ship_id}")
            self.sdk.assign_crew_to_ship(station_id, ship_id, pilot["id"], "pilot")

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

    def _select_ship_to_buy(self, station_id, budget):
        shipyard = self.sdk.shop_list_ship(station_id)
        if not shipyard:
            return None

        def ratio(ship):
            price = max(ship.get("price", 1.0), 1.0)
            cargo = ship.get("cargo_capacity", 1.0)
            reactor = ship.get("reactor_power", 1.0)
            return (cargo * (1.0 + reactor)) / price

        affordable = [ship for ship in shipyard if ship.get("price", 0.0) + MODULE_COST <= budget]
        if not affordable:
            return None
        return max(affordable, key=ratio)

    def _buy_new_ship_if_possible(self, station_id, market_prices, planets):
        status = self.sdk.get_player_status()
        ships = status.get("ships", [])
        if len(ships) >= self.max_ships:
            return False

        reserve = self._reserve(status)
        budget = status["money"] - reserve
        if budget <= MODULE_COST:
            return False

        candidate = self._select_ship_to_buy(station_id, budget)
        if candidate is None:
            return False

        self._log_action(
            f"Buying new ship {candidate['id']} (price {round(candidate['price'], 2)}) - fleet {len(ships)+1}/{self.max_ships}"
        )
        bought = self.sdk.buy_ship(station_id, candidate["id"])
        ship_id = bought.get("id", candidate["id"])
        self._record_improvement("ships")

        family = self._default_family(market_prices, planets)
        ship = self.sdk.get_ship_status(ship_id)
        self._ensure_ship_setup(station_id, ship, family)
        return True

    def _expand_existing_ships(self, station_id, station_pos, market_prices, planets):
        status = self.sdk.get_player_status()
        reserve = self._reserve(status)
        ships = sorted(status.get("ships", []), key=lambda s: len(s.get("modules", {})))
        spent_any = False

        for ship in ships:
            status = self.sdk.get_player_status()
            if status["money"] <= reserve + MODULE_COST:
                return spent_any

            ship = self.sdk.get_ship_status(ship["id"])
            if ship.get("position") != station_pos:
                continue

            family = self._best_family_for_ship(ship, market_prices)
            if not self._ship_has_module_family(ship, family):
                family = self._default_family(market_prices, planets)
            try:
                self._log_action(f"Expanding ship {ship['id']} with one more {family} module")
                self._buy_module_and_operator(station_id, ship["id"], family)
                self._record_improvement("modules")
                spent_any = True
            except SimeisError as err:
                self._log_verbose(f"Expansion skipped for ship {ship['id']}: {err}")

        return spent_any

    def _upgrade_price(self, upgrade_info, name):
        data = upgrade_info.get(name)
        if not isinstance(data, dict):
            return None
        return data.get("price")

    def _try_upgrade_mobility(self, station_id, station_pos):
        status = self.sdk.get_player_status()
        reserve = self._reserve(status)
        if status["money"] <= max(reserve, MOBILITY_MIN_BANK):
            return False

        ships = []
        for raw_ship in status.get("ships", []):
            ship = self.sdk.get_ship_status(raw_ship["id"])
            if ship.get("position") != station_pos:
                continue
            ships.append(ship)

        ships.sort(key=lambda s: (s.get("reactor_power", 0), s.get("cargo", {}).get("capacity", 0.0)))

        for ship in ships:
            ship_id = ship["id"]
            cur_status = self.sdk.get_player_status()
            floor = max(reserve, MOBILITY_MIN_BANK)
            if cur_status["money"] <= floor:
                return False

            options = []

            pilot_id = ship.get("pilot")
            if pilot_id is not None:
                pilot = self._mapping_value(ship.get("crew", {}), pilot_id)
                if pilot is not None:
                    pilot_price = self._upgrade_crew_price(pilot)
                    pilot_rank = pilot.get("rank", 1)
                    if cur_status["money"] > floor + pilot_price:
                        pilot_weight = 3.6 if pilot_rank < 5 else 2.1 if pilot_rank < 8 else 1.0
                        options.append(
                            {
                                "kind": "pilot",
                                "score": pilot_weight / max(pilot_price, 1.0),
                                "price": pilot_price,
                                "pilot_id": pilot_id,
                            }
                        )

            try:
                upg = self.sdk.get(f"/station/{station_id}/shipyard/upgrade/{ship_id}")
            except SimeisError:
                continue

            cargo_price = self._upgrade_price(upg, "CargoExpansion")
            if cargo_price is not None and cur_status["money"] > floor + cargo_price:
                cargo_cap = ship.get("cargo", {}).get("capacity", 0.0)
                cargo_weight = 3.0 if cargo_cap < 900.0 else 1.6
                options.append(
                    {
                        "kind": "cargo",
                        "score": cargo_weight / max(cargo_price, 1.0),
                        "price": cargo_price,
                    }
                )

            reactor_price = self._upgrade_price(upg, "ReactorUpgrade")
            if reactor_price is not None and cur_status["money"] > floor + reactor_price:
                reactor_power = ship.get("reactor_power", 0)
                reactor_weight = 2.8 if reactor_power < 6 else 1.3
                options.append(
                    {
                        "kind": "reactor",
                        "score": reactor_weight / max(reactor_price, 1.0),
                        "price": reactor_price,
                    }
                )

            if not options:
                continue

            best = max(options, key=lambda x: x["score"])
            try:
                if best["kind"] == "pilot":
                    pid = best["pilot_id"]
                    self._log_action(
                        f"Upgrading pilot {pid} on ship {ship_id} (estimated {round(best['price'], 2)})"
                    )
                    self.sdk.post(f"/station/{station_id}/crew/upgrade/ship/{ship_id}/{pid}")
                    self._record_improvement("pilot_upgrades")
                    return True

                if best["kind"] == "cargo":
                    self._log_action(f"Upgrading cargo on ship {ship_id} (price {round(best['price'], 2)})")
                    self.sdk.post(f"/station/{station_id}/shipyard/upgrade/{ship_id}/CargoExpansion")
                    self._record_improvement("cargo_upgrades")
                    return True

                if best["kind"] == "reactor":
                    self._log_action(f"Upgrading reactor on ship {ship_id} (price {round(best['price'], 2)})")
                    self.sdk.post(f"/station/{station_id}/shipyard/upgrade/{ship_id}/ReactorUpgrade")
                    self._record_improvement("reactor_upgrades")
                    return True
            except SimeisError:
                pass

        return False

    def _try_upgrade_operators(self, station_id):
        status = self.sdk.get_player_status()
        reserve = self._reserve(status)
        if status["money"] <= max(reserve, OP_UPGRADE_MIN_BANK):
            return

        for ship in status.get("ships", []):
            ship = self.sdk.get_ship_status(ship["id"])
            for module in ship.get("modules", {}).values():
                operator_id = module.get("operator")
                if operator_id is None:
                    continue
                operator = self._mapping_value(ship.get("crew", {}), operator_id)
                if operator is None:
                    continue
                up_price = self._upgrade_crew_price(operator)
                cur_status = self.sdk.get_player_status()
                if cur_status["money"] <= max(reserve, OP_UPGRADE_MIN_BANK) + up_price:
                    continue
                try:
                    self._log_action(
                        f"Upgrading operator {operator_id} on ship {ship['id']} (estimated {round(up_price, 2)})"
                    )
                    self.sdk.post(f"/station/{station_id}/crew/upgrade/ship/{ship['id']}/{operator_id}")
                    self._record_improvement("operator_upgrades")
                    return
                except SimeisError:
                    continue

    def _invest_aggressively(self, station_id, station_pos, market_prices, planets):
        start_status = self.sdk.get_player_status()
        ships_count = len(start_status.get("ships", []))
        rush_target = min(self.max_ships, 6)

        changed = True
        max_passes = 8
        passes = 0
        while changed and passes < max_passes:
            changed = False
            passes += 1

            if ships_count < rush_target:
                if self._buy_new_ship_if_possible(station_id, market_prices, planets):
                    ships_count += 1
                    changed = True
                    continue
                if self._try_upgrade_mobility(station_id, station_pos):
                    changed = True
                    continue
                if self._expand_existing_ships(station_id, station_pos, market_prices, planets):
                    changed = True
                    continue
            else:
                if self._expand_existing_ships(station_id, station_pos, market_prices, planets):
                    changed = True
                    continue
                if self._buy_new_ship_if_possible(station_id, market_prices, planets):
                    ships_count += 1
                    changed = True
                    continue
                if self._try_upgrade_mobility(station_id, station_pos):
                    changed = True
                    continue

            self._try_upgrade_operators(station_id)

    def _position_avg_price(self, resource):
        pos = self.trade_positions.get(resource)
        if not pos or pos.get("qty", 0.0) <= EPS:
            return None
        return pos["spent"] / max(pos["qty"], EPS)

    def _maybe_open_trade(self, station_id, market_prices, status):
        if not self.market_enabled and not self._ensure_trader_for_market(station_id):
            return False

        if not self._ensure_trader_for_market(station_id):
            return False

        reserve = self._reserve(status)
        if status["money"] <= max(reserve, TRADE_MIN_BANK):
            return False

        budget = min(status["money"] - reserve, status["money"] * TRADE_BUDGET_RATIO)
        if budget < 2500.0:
            return False

        best_resource = None
        best_score = 1.0
        for resource, price in market_prices.items():
            if resource in ("Fuel", "Hull"):
                continue
            ratio = self._resource_price_ratio(resource, price)
            if ratio < best_score:
                best_score = ratio
                best_resource = resource

        if best_resource is None or best_score > 0.22:
            return False

        price = float(market_prices.get(best_resource, 0.0))
        if price <= EPS:
            return False

        amount = int(budget / price)
        if amount <= 0:
            return False

        amount = min(amount, 240)
        try:
            self._log_action(
                f"Trade buy {amount} {best_resource} at {round(price, 3)} (price ratio {round(best_score, 3)})"
            )
            self.sdk.buy_resource(station_id, best_resource, amount)
            self._record_improvement("trade_buys")
            pos = self.trade_positions.setdefault(
                best_resource,
                {"qty": 0.0, "spent": 0.0, "opened": self.loop_count},
            )
            pos["qty"] += amount
            pos["spent"] += amount * price
            pos["opened"] = self.loop_count
            return True
        except SimeisError as err:
            if self._is_no_trader_error(err):
                self.trader_ready = False
                self.last_trader_check_loop = self.loop_count - TRADER_RECHECK_LOOPS
                if not self._ensure_trader_for_market(station_id):
                    self.market_enabled = False
                    return False
                try:
                    self.sdk.buy_resource(station_id, best_resource, amount)
                    self._record_improvement("trade_buys")
                    pos = self.trade_positions.setdefault(
                        best_resource,
                        {"qty": 0.0, "spent": 0.0, "opened": self.loop_count},
                    )
                    pos["qty"] += amount
                    pos["spent"] += amount * price
                    pos["opened"] = self.loop_count
                    return True
                except SimeisError as err2:
                    self._log_verbose(f"Trade buy retry failed for {best_resource}: {err2}")
                    return False
            self._log_verbose(f"Trade buy failed for {best_resource}: {err}")
            return False

    def _sell_station_resources(self, station_id, market_prices):
        if not self.market_enabled and not self._ensure_trader_for_market(station_id):
            return 0.0

        if not self._ensure_trader_for_market(station_id):
            return 0.0

        cycle_gain = 0.0
        resources = self.sdk.get_station_resources(station_id)
        for res, amnt in resources.items():
            if res in ["Fuel", "Hull"] or amnt <= 0.0:
                continue

            to_sell = float(amnt)
            pos = self.trade_positions.get(res)
            if pos and pos.get("qty", 0.0) > EPS:
                avg_buy = self._position_avg_price(res)
                now_price = float(market_prices.get(res, 0.0))
                hold_age = self.loop_count - int(pos.get("opened", self.loop_count))
                should_close = False
                if avg_buy is not None and now_price > EPS:
                    if now_price >= avg_buy * TRADE_TARGET_PROFIT:
                        should_close = True
                    elif now_price <= avg_buy * TRADE_STOP_LOSS:
                        should_close = True
                    elif hold_age >= TRADE_MAX_HOLD:
                        should_close = True

                if not should_close:
                    held_qty = min(float(pos.get("qty", 0.0)), to_sell)
                    to_sell = max(0.0, to_sell - held_qty)

            if to_sell <= EPS:
                continue

            try:
                got = self.sdk.sell_resource(station_id, res, to_sell)
                cycle_gain += got["added_money"]
                self._log_verbose(
                    f"Sold {round(to_sell, 3)} {res} for {round(got['added_money'], 2)}"
                )

                pos = self.trade_positions.get(res)
                if pos and pos.get("qty", 0.0) > EPS:
                    dec = min(pos["qty"], to_sell)
                    avg = self._position_avg_price(res)
                    pos["qty"] -= dec
                    if avg is not None:
                        pos["spent"] = max(0.0, pos["spent"] - dec * avg)
                    if pos["qty"] <= EPS:
                        self.trade_positions.pop(res, None)
            except SimeisError as err:
                if self._is_no_trader_error(err):
                    self.trader_ready = False
                    self.last_trader_check_loop = self.loop_count - TRADER_RECHECK_LOOPS
                    if not self._ensure_trader_for_market(station_id):
                        self.market_enabled = False
                        return cycle_gain
                    try:
                        got = self.sdk.sell_resource(station_id, res, to_sell)
                        cycle_gain += got["added_money"]
                        self._log_verbose(
                            f"Sold {round(to_sell, 3)} {res} for {round(got['added_money'], 2)}"
                        )
                        continue
                    except SimeisError as err2:
                        self._log_verbose(f"Sell retry failed for {res}: {err2}")
                        return cycle_gain
                self._log_verbose(f"Sell {res} failed: {err}")
        return cycle_gain

    def _maintain_ship_in_station(self, station_id, ship_id):
        # Refuel – fuel is cheap, always do it
        try:
            fuel = self.sdk.buy_fuel_for_refuel(station_id, ship_id)
            if fuel is not None:
                self._log_verbose(f"Ship {ship_id} refuelled for {round(fuel['removed_money'], 2)}")
            self.sdk.refuel_ship(station_id, ship_id)
        except SimeisError:
            pass

        # Hull repair – check budget before buying to avoid bankruptcy
        try:
            ship = self.sdk.get_ship_status(ship_id)
            hull_needed = int(ship.get("hull_decay", 0))
            if hull_needed <= 0:
                return
            hull_cost_est = hull_needed * 3.5   # generous upper bound (base 2.0 + fees + price swing)
            status = self.sdk.get_player_status()
            reserve = self._reserve(status)
            if status["money"] <= reserve + hull_cost_est:
                self._log_action(
                    f"Ship {ship_id} hull damage {hull_needed} but only {round(status['money'],1)} cr – skipping repair"
                )
                return
            hull = self.sdk.buy_hull_for_repair(station_id, ship_id)
            if hull is not None:
                self._log_verbose(f"Ship {ship_id} repaired hull for {round(hull['removed_money'], 2)}")
            self.sdk.repair_ship(station_id, ship_id)
        except SimeisError:
            pass

    def _drive_ship(self, ship, station_id, station_pos, planets, market_prices):
        ship_id = ship["id"]
        state = self._state_name(ship.get("state"))
        cargo = ship.get("cargo", {})
        cargo_usage = float(cargo.get("usage", 0.0))
        at_station = ship.get("position") == station_pos

        if state != "Idle":
            return

        family = self._best_family_for_ship(ship, market_prices)
        if not self._ship_has_module_family(ship, family):
            family = self._default_family(market_prices, planets)

        if at_station:
            if cargo_usage > EPS:
                self._log_action(f"Unloading ship {ship_id} at station")
                try:
                    self.sdk.return_station_and_unload_all(station_id, ship_id)
                except SimeisError:
                    return
                # SELL IMMEDIATELY after unload so we have money before paying for hull repair
                sold = self._sell_station_resources(station_id, market_prices)
                if sold > 0.0:
                    self._log_action(f"Sold cargo for {round(sold, 2)} cr")

            self._maintain_ship_in_station(station_id, ship_id)

            target = self._best_planet_for_ship(ship, planets)
            if target is None:
                return
            self._log_action(f"Dispatch ship {ship_id} → {'solid' if target['solid'] else 'gas'} planet {target['position']}")
            self._safe_travel(ship_id, target["position"], wait_end=False)
            return

        if cargo_usage > EPS:
            self._log_action(f"Ship {ship_id} full – returning to station")
            self._safe_travel(ship_id, station_pos, wait_end=False)
            return

        try:
            self._log_action(f"Ship {ship_id} starts extraction")
            self.sdk.start_extraction(ship_id)
        except SimeisError:
            target = self._best_planet_for_ship(ship, planets)
            if target is None:
                return
            self._log_action(f"Ship {ship_id} repositions to {target['position']}")
            self._safe_travel(ship_id, target["position"], wait_end=False)

    def gameloop(self):
        self._log_action(f"Aggressive mode enabled - max ships: {self.max_ships}")
        while True:
            try:
                self.loop_count += 1
                self._safe_tick()
                status = self.sdk.get_player_status()
                if status["money"] <= 0:
                    print("You lost")
                    return

                station_id = status["stations"][0]
                self.last_station_id = station_id
                station = self.sdk.get_station_status(station_id)
                station_pos = station.get("position")

                market_prices = self.sdk.get_market_prices()
                self._record_prices(market_prices)
                if self._planets_cache is None:
                    self._planets_cache = self.sdk.scan_planets(station_id)
                planets = self._planets_cache

                self._invest_aggressively(station_id, station_pos, market_prices, planets)

                status = self.sdk.get_player_status()
                ships = status.get("ships", [])

                for ship in ships:
                    ship = self.sdk.get_ship_status(ship["id"])
                    self._log_ship_state(ship, "Fleet")
                    self._ensure_ship_setup(
                        station_id,
                        ship,
                        self._best_family_for_ship(ship, market_prices),
                        station_pos,
                    )
                    self._drive_ship(ship, station_id, station_pos, planets, market_prices)

                sold = 0.0
                if (self.loop_count % 4) == 0:
                    sold = self._sell_station_resources(station_id, market_prices)
                if sold > 0.0:
                    self._log_action(f"Sold station cargo for {round(sold, 2)} credits")

                status = self.sdk.get_player_status()
                if (self.loop_count % 2) == 0:
                    self._maybe_open_trade(station_id, market_prices, status)
                    status = self.sdk.get_player_status()

                print(
                    "Money: {} | Costs: {} | Ships: {} | Reserve: {} | {}".format(
                        round(status["money"], 2),
                        round(status["costs"], 2),
                        len(status.get("ships", [])),
                        round(self._reserve(status), 2),
                        self._improvement_summary(),
                    )
                )
                time.sleep(LOOP_DELAY_SEC)

            except SimeisError as err:
                self._log_action(f"SDK error: {err}")
                time.sleep(0.5)
            except Exception as err:
                self._log_action(f"Unexpected error: {err}")
                time.sleep(0.5)


if __name__ == "__main__":
    args = [
        arg
        for arg in sys.argv[1:]
        if arg != "--verbose" and not arg.startswith("--max-ships=")
    ]
    verbose = "--verbose" in sys.argv[1:]
    max_ships = 10
    for arg in sys.argv[1:]:
        if arg.startswith("--max-ships="):
            max_ships = int(arg.split("=", 1)[1])

    if len(args) < 3:
        print("Usage: python3.py ./client_agressif.py <username> <IP> <port> [--verbose] [--max-ships=N]")
        sys.exit(1)

    name = args[0]
    ip = args[1]
    port = int(args[2])
    game = Game(name, ip, port, verbose=verbose, max_ships=max_ships)
    game.gameloop()
