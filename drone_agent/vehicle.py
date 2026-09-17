"""Thin, thread-safe wrapper around pymavlink for an ArduCopter vehicle.

A background thread reads every MAVLink message and caches the latest state,
so the blocking command helpers below can simply poll that cache.
"""

import math
import threading
import time
from collections import deque

from pymavlink import mavutil

mavlink = mavutil.mavlink

EARTH_RADIUS_M = 6378137.0

# SET_POSITION_TARGET type_mask: use position only, ignore velocity/accel/yaw
POSITION_ONLY_MASK = (
    mavlink.POSITION_TARGET_TYPEMASK_VX_IGNORE
    | mavlink.POSITION_TARGET_TYPEMASK_VY_IGNORE
    | mavlink.POSITION_TARGET_TYPEMASK_VZ_IGNORE
    | mavlink.POSITION_TARGET_TYPEMASK_AX_IGNORE
    | mavlink.POSITION_TARGET_TYPEMASK_AY_IGNORE
    | mavlink.POSITION_TARGET_TYPEMASK_AZ_IGNORE
    | mavlink.POSITION_TARGET_TYPEMASK_YAW_IGNORE
    | mavlink.POSITION_TARGET_TYPEMASK_YAW_RATE_IGNORE
)


class VehicleError(Exception):
    """A command was rejected or did not complete."""


def distance_m(lat1, lon1, lat2, lon2):
    """Approximate ground distance in metres (fine for short ranges)."""
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dlat, dlon) * EARTH_RADIUS_M


def offset_location(lat, lon, north_m, east_m):
    """Return the lat/lon that is north_m / east_m away from lat/lon."""
    new_lat = lat + math.degrees(north_m / EARTH_RADIUS_M)
    new_lon = lon + math.degrees(east_m / (EARTH_RADIUS_M * math.cos(math.radians(lat))))
    return new_lat, new_lon


class Vehicle:
    def __init__(self, connection="tcp:127.0.0.1:5762", timeout=30):
        self.conn = mavutil.mavlink_connection(connection, source_system=254, source_component=190)
        hb = self.conn.wait_heartbeat(timeout=timeout)
        if hb is None:
            raise VehicleError(f"No heartbeat from {connection}. Are Gazebo and SITL running?")
        self.sysid = self.conn.target_system
        self.compid = self.conn.target_component

        self._lock = threading.Lock()
        self._latest = {}
        self._acks = {}
        self._statustext = deque(maxlen=30)
        self._home = None
        self._running = True
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

        self.conn.mav.request_data_stream_send(
            self.sysid, self.compid, mavlink.MAV_DATA_STREAM_ALL, 5, 1
        )
        self._wait(
            lambda: self._get("HEARTBEAT") is not None and self._get("GLOBAL_POSITION_INT") is not None,
            10, "vehicle state",
        )
        self.request_home()

    # ------------------------------------------------------------------ io
    def _read_loop(self):
        last_hb = 0.0
        while self._running:
            now = time.time()
            if now - last_hb > 1.0:
                self.conn.mav.heartbeat_send(mavlink.MAV_TYPE_GCS, mavlink.MAV_AUTOPILOT_INVALID, 0, 0, 0)
                last_hb = now
            msg = self.conn.recv_match(blocking=True, timeout=0.5)
            if msg is None or msg.get_srcSystem() != self.sysid:
                continue
            mtype = msg.get_type()
            with self._lock:
                if mtype == "HEARTBEAT" and msg.type == mavlink.MAV_TYPE_GCS:
                    continue
                self._latest[mtype] = msg
                if mtype == "COMMAND_ACK":
                    self._acks[msg.command] = (time.time(), msg.result)
                elif mtype == "STATUSTEXT":
                    self._statustext.append((time.time(), msg.text))
                elif mtype == "HOME_POSITION":
                    self._home = (msg.latitude / 1e7, msg.longitude / 1e7)

    def close(self):
        self._running = False
        self._reader.join(timeout=2)
        self.conn.close()

    def _get(self, mtype):
        with self._lock:
            return self._latest.get(mtype)

    def _wait(self, predicate, timeout, what):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return
            time.sleep(0.2)
        raise VehicleError(f"Timed out after {timeout:.0f}s waiting for {what}")

    def messages_since(self, t):
        with self._lock:
            return [text for ts, text in self._statustext if ts >= t]

    def _command(self, command, *params, timeout=5):
        """Send COMMAND_LONG and wait for its ACK. Returns on success, raises otherwise."""
        params = list(params) + [0] * (7 - len(params))
        sent = time.time()
        self.conn.mav.command_long_send(self.sysid, self.compid, command, 0, *params)
        try:
            self._wait(lambda: self._acks.get(command, (0,))[0] >= sent, timeout, "command ack")
        except VehicleError:
            raise VehicleError(f"No response to {mavlink.enums['MAV_CMD'][command].name}")
        result = self._acks[command][1]
        if result != mavlink.MAV_RESULT_ACCEPTED:
            name = mavlink.enums["MAV_RESULT"][result].name
            time.sleep(0.5)  # give the autopilot a moment to explain itself
            reasons = self.messages_since(sent)
            detail = f" Autopilot says: {'; '.join(reasons)}" if reasons else ""
            raise VehicleError(f"{mavlink.enums['MAV_CMD'][command].name} rejected ({name}).{detail}")

    # --------------------------------------------------------------- state
    @property
    def mode(self):
        hb = self._get("HEARTBEAT")
        return mavutil.mode_string_v10(hb) if hb else "UNKNOWN"

    @property
    def armed(self):
        hb = self._get("HEARTBEAT")
        return bool(hb and hb.base_mode & mavlink.MAV_MODE_FLAG_SAFETY_ARMED)

    @property
    def position(self):
        """(lat, lon, relative_alt_m)"""
        p = self._get("GLOBAL_POSITION_INT")
        return p.lat / 1e7, p.lon / 1e7, p.relative_alt / 1000.0

    @property
    def home(self):
        with self._lock:
            return self._home

    def request_home(self):
        self.conn.mav.command_long_send(
            self.sysid, self.compid, mavlink.MAV_CMD_REQUEST_MESSAGE, 0,
            mavlink.MAVLINK_MSG_ID_HOME_POSITION, 0, 0, 0, 0, 0, 0,
        )

    def distance_from_home(self, lat=None, lon=None):
        if self.home is None:
            return None
        if lat is None:
            lat, lon, _ = self.position
        return distance_m(self.home[0], self.home[1], lat, lon)

    def status(self):
        lat, lon, alt = self.position
        vfr = self._get("VFR_HUD")
        gps = self._get("GPS_RAW_INT")
        batt = self._get("SYS_STATUS")
        dist = self.distance_from_home()
        return {
            "mode": self.mode,
            "armed": self.armed,
            "altitude_m": round(alt, 2),
            "latitude": round(lat, 7),
            "longitude": round(lon, 7),
            "distance_from_home_m": None if dist is None else round(dist, 1),
            "heading_deg": vfr.heading if vfr else None,
            "groundspeed_m_s": round(vfr.groundspeed, 2) if vfr else None,
            "climb_m_s": round(vfr.climb, 2) if vfr else None,
            "gps_fix_type": gps.fix_type if gps else None,
            "gps_satellites": gps.satellites_visible if gps else None,
            "battery_percent": batt.battery_remaining if batt else None,
            "recent_autopilot_messages": self.messages_since(time.time() - 30)[-8:],
        }

    # ------------------------------------------------------------ commands
    def set_mode(self, name, timeout=5):
        name = name.upper()
        mapping = self.conn.mode_mapping()
        if name not in mapping:
            raise VehicleError(f"Unknown mode {name}. Valid: {', '.join(sorted(mapping))}")
        self._command(
            mavlink.MAV_CMD_DO_SET_MODE,
            mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, mapping[name],
        )
        self._wait(lambda: self.mode == name, timeout, f"mode {name}")

    def arm(self, timeout=10):
        self._command(mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 1)
        self._wait(lambda: self.armed, timeout, "motors to arm")
        self.request_home()  # ArduPilot resets home on arming

    def disarm(self, timeout=10):
        self._command(mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0)
        self._wait(lambda: not self.armed, timeout, "motors to disarm")

    def takeoff(self, altitude, timeout=60):
        self._command(mavlink.MAV_CMD_NAV_TAKEOFF, 0, 0, 0, 0, 0, 0, altitude)
        self._wait(lambda: self.position[2] >= altitude * 0.95, timeout, f"altitude {altitude} m")

    def goto(self, lat, lon, altitude, timeout=120, tolerance_m=1.0):
        self.conn.mav.set_position_target_global_int_send(
            0, self.sysid, self.compid,
            mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT, POSITION_ONLY_MASK,
            int(lat * 1e7), int(lon * 1e7), altitude,
            0, 0, 0, 0, 0, 0, 0, 0,
        )

        def arrived():
            clat, clon, calt = self.position
            return distance_m(clat, clon, lat, lon) <= tolerance_m and abs(calt - altitude) <= 0.5

        self._wait(arrived, timeout, "arrival at target")

    def wait_until_disarmed(self, timeout):
        self._wait(lambda: not self.armed, timeout, "landing and disarm")
