#!/usr/bin/env python3
"""
Tests property-based pour Simeis.

Usage:
  python tests/propertybased.py                 # rapide (CI PR)
  python tests/propertybased.py --heavy         # long (CI tests lourds)
  python tests/propertybased.py --time 30       # durée personnalisée
"""

from __future__ import annotations

import argparse
import math
import random
import sys
import time


def create_property_based_test(f, regressions=None, time_test=10):
    if regressions is None:
        regressions = []

    tstart = time.time()
    i = 0
    while (time.time() - tstart) < time_test:
        if i < len(regressions):
            seed = regressions[i]
        else:
            seed = random.randrange(0, 2**64)
        random.seed(seed)
        try:
            f()
            print("Test", f.__name__, i, "OK", f"(seed={seed})")
        except AssertionError as err:
            print("Test", f.__name__, "failed with seed", seed)
            print(err)
            sys.exit(1)
        i += 1


def get_dist(a, b):
    return math.sqrt(((a[0] - b[0]) ** 2) + ((a[1] - b[1]) ** 2) + ((a[2] - b[2]) ** 2))


def addition():
    x = random.randrange(0, 10000)
    y = random.randrange(0, 10000)

    # Propriétés de base de l'addition sur entiers.
    assert x + y == y + x
    assert (x + y) - x == y
    assert (x + y) - y == x


def distance():
    x1 = random.randrange(-100, 100)
    y1 = random.randrange(-100, 100)
    z1 = random.randrange(-100, 100)
    a = (x1, y1, z1)

    x2 = random.randrange(-100, 100)
    y2 = random.randrange(-100, 100)
    z2 = random.randrange(-100, 100)
    b = (x2, y2, z2)

    expected = math.sqrt(
        ((a[0] - b[0]) ** 2) + ((a[1] - b[1]) ** 2) + ((a[2] - b[2]) ** 2)
    )
    got = get_dist(a, b)

    assert got >= 0.0
    assert math.isclose(got, expected, rel_tol=0.0, abs_tol=1e-9)

    if a == b:
        assert got == 0.0
    else:
        assert got > 0.0


def parse_args():
    parser = argparse.ArgumentParser(description="Property-based tests Simeis")
    parser.add_argument(
        "--heavy",
        action="store_true",
        help="Active la version longue des tests (CI tests lourds).",
    )
    parser.add_argument(
        "--time",
        type=int,
        default=None,
        help="Durée totale (secondes) par test. Surcharge le mode rapide/lourd.",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.time is not None:
        addition_time = args.time
        distance_time = args.time
    elif args.heavy:
        addition_time = 120
        distance_time = 120
    else:
        addition_time = 3
        distance_time = 10

    print(
        "Mode:",
        "heavy" if args.heavy else "fast",
        f"| addition={addition_time}s | distance={distance_time}s",
    )

    create_property_based_test(addition, time_test=addition_time)
    create_property_based_test(
        distance,
        regressions=[4480881574280375424],
        time_test=distance_time,
    )
    print("Tous les tests property-based ont réussi.")


if __name__ == "__main__":
    main()
