"""Smoke test for vehicle.py (no Claude API needed).

Start Gazebo and SITL first, then run:  python test_vehicle.py
Flies: takeoff 5 m -> 10 m north -> 5 m east -> land.
"""

import json

from vehicle import Vehicle, VehicleError, offset_location


def show(step, v):
    s = v.status()
    print(f"[{step}] mode={s['mode']} armed={s['armed']} alt={s['altitude_m']} m "
          f"home_dist={s['distance_from_home_m']} m")


def main():
    v = Vehicle()
    show("connected", v)
    print("status:", json.dumps(v.status(), indent=2))

    v.set_mode("GUIDED")
    v.arm()
    show("armed", v)
    v.takeoff(5)
    show("takeoff", v)

    for north, east in [(10, 0), (0, 5)]:
        lat, lon, _ = v.position
        v.goto(*offset_location(lat, lon, north, east), 5)
        show(f"moved N{north} E{east}", v)

    v.set_mode("LAND")
    v.wait_until_disarmed(timeout=120)
    show("landed", v)

    try:
        v.set_mode("NOT_A_MODE")
    except VehicleError as e:
        print("expected error:", str(e)[:80])
    v.close()
    print("OK")


if __name__ == "__main__":
    main()
