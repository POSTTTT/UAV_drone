"""Drone tools for an LLM agent, independent of any LLM provider.

Each tool is a plain function plus a JSON schema in the OpenAI "function calling"
format, which Ollama, LM Studio, llama.cpp, vLLM and most hosted APIs accept.
"""

import json
import time

from vehicle import Vehicle, VehicleError, offset_location

# Safety limits, enforced in code regardless of what the model asks for
MAX_ALTITUDE_M = 50.0
MAX_DISTANCE_FROM_HOME_M = 300.0


class ToolError(Exception):
    """A tool could not do what was asked; the message is returned to the model."""


class DroneTools:
    def __init__(self, vehicle: Vehicle):
        self.vehicle = vehicle

    # -------------------------------------------------------------- helpers
    def _status(self):
        return json.dumps(self.vehicle.status())

    def _run(self, action):
        """Run a vehicle action, converting failures into a ToolError for the model."""
        try:
            action()
        except VehicleError as e:
            raise ToolError(f"{e} Current status: {self._status()}")
        return self._status()

    def _check_altitude(self, altitude_m):
        if not 1.0 <= altitude_m <= MAX_ALTITUDE_M:
            raise ToolError(f"altitude_m must be between 1 and {MAX_ALTITUDE_M:.0f}.")

    def _goto_checked(self, lat, lon, altitude_m):
        v = self.vehicle
        if not v.armed or v.position[2] < 0.5:
            raise ToolError("The drone is not flying. Take off first.")
        self._check_altitude(altitude_m)
        dist = v.distance_from_home(lat, lon)
        if dist is not None and dist > MAX_DISTANCE_FROM_HOME_M:
            raise ToolError(
                f"Target is {dist:.0f} m from home, beyond the {MAX_DISTANCE_FROM_HOME_M:.0f} m limit."
            )

        def action():
            if v.mode != "GUIDED":
                v.set_mode("GUIDED")
            v.goto(lat, lon, altitude_m)
        return self._run(action)

    # ---------------------------------------------------------------- tools
    def get_status(self):
        return self._status()

    def set_mode(self, mode):
        return self._run(lambda: self.vehicle.set_mode(mode))

    def arm(self):
        def action():
            self.vehicle.set_mode("GUIDED")
            self.vehicle.arm()
        return self._run(action)

    def disarm(self):
        if self.vehicle.position[2] > 0.5:
            raise ToolError("Refusing to disarm in the air; land first.")
        return self._run(self.vehicle.disarm)

    def takeoff(self, altitude_m):
        self._check_altitude(altitude_m)
        v = self.vehicle

        def action():
            if v.mode != "GUIDED":
                v.set_mode("GUIDED")
            if not v.armed:
                v.arm()
            v.takeoff(altitude_m)
        return self._run(action)

    def fly_relative(self, north_m, east_m, altitude_m):
        lat, lon, _ = self.vehicle.position
        target_lat, target_lon = offset_location(lat, lon, north_m, east_m)
        return self._goto_checked(target_lat, target_lon, altitude_m)

    def fly_to_location(self, latitude, longitude, altitude_m):
        return self._goto_checked(latitude, longitude, altitude_m)

    def hover(self, seconds):
        if not 1 <= seconds <= 120:
            raise ToolError("seconds must be between 1 and 120.")
        time.sleep(seconds)
        return self._status()

    def land(self):
        def action():
            self.vehicle.set_mode("LAND")
            self.vehicle.wait_until_disarmed(timeout=120)
        return self._run(action)

    def return_to_launch(self):
        def action():
            self.vehicle.set_mode("RTL")
            self.vehicle.wait_until_disarmed(timeout=300)
        return self._run(action)

    # ------------------------------------------------------------- dispatch
    def call(self, name, arguments):
        """Run tool `name` with a dict of arguments. Always returns (text, is_error)."""
        if name not in TOOL_PARAMS:
            return f"Error: unknown tool '{name}'. Available: {', '.join(TOOL_PARAMS)}", True
        params = TOOL_PARAMS[name]
        missing = [p for p in params if p not in arguments]
        if missing:
            return f"Error: missing argument(s) {missing} for {name}.", True
        try:
            kwargs = {p: _coerce(arguments[p], NUMBER_PARAMS.get(p)) for p in params}
            return getattr(self, name)(**kwargs), False
        except ToolError as e:
            return f"Error: {e}", True
        except (TypeError, ValueError) as e:
            return f"Error: bad arguments for {name}: {e}", True


def _coerce(value, is_number):
    # Small local models often send numbers as strings ("10")
    return float(value) if is_number else str(value)


def _number(description):
    return {"type": "number", "description": description}


def _function(name, description, properties=None):
    properties = properties or {}
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(properties),
            },
        },
    }


TOOL_SCHEMAS = [
    _function("get_status",
              "Get the drone's current state: flight mode, armed, altitude, position, distance from "
              "home, speed, GPS, battery and recent autopilot messages."),
    _function("set_mode", "Change the flight mode.", {
        "mode": {"type": "string",
                 "description": "ArduCopter mode, e.g. GUIDED, LOITER, BRAKE, LAND, RTL, ALT_HOLD."},
    }),
    _function("arm", "Switch to GUIDED mode and arm the motors (drone must be on the ground). "
                     "Usually not needed: takeoff arms automatically."),
    _function("disarm", "Disarm the motors. Only when the drone is on the ground."),
    _function("takeoff",
              "Take off vertically to an altitude and wait until reached. Arms automatically.", {
                  "altitude_m": _number(f"Target altitude above home in metres (1-{MAX_ALTITUDE_M:.0f})."),
              }),
    _function("fly_relative",
              "Fly to a point offset from the drone's CURRENT position and wait until it arrives. "
              "Use negative values for south/west. Example: 10 m north = north_m 10, east_m 0.", {
                  "north_m": _number("Metres north (negative = south)."),
                  "east_m": _number("Metres east (negative = west)."),
                  "altitude_m": _number("Altitude above home to fly at, in metres."),
              }),
    _function("fly_to_location", "Fly to an absolute GPS coordinate and wait until it arrives.", {
        "latitude": _number("Target latitude in decimal degrees."),
        "longitude": _number("Target longitude in decimal degrees."),
        "altitude_m": _number("Altitude above home in metres."),
    }),
    _function("hover", "Hold the current position for some seconds, then report status.", {
        "seconds": _number("How long to wait (1-120)."),
    }),
    _function("land", "Land at the current position and wait until landed and disarmed."),
    _function("return_to_launch", "Fly back to the takeoff point, land, and wait until disarmed."),
]

TOOL_PARAMS = {
    s["function"]["name"]: list(s["function"]["parameters"]["properties"]) for s in TOOL_SCHEMAS
}
NUMBER_PARAMS = {
    p: spec["type"] == "number"
    for s in TOOL_SCHEMAS
    for p, spec in s["function"]["parameters"]["properties"].items()
}

SYSTEM_PROMPT = f"""You control a simulated quadcopter (ArduPilot SITL + Gazebo) using the provided tools.
The operator gives instructions in plain language. Carry them out by calling tools.

Rules:
- Call one tool at a time and wait for its result before the next step.
- takeoff arms the drone and switches to GUIDED mode by itself.
- Altitudes are metres above the takeoff point. North/east distances are metres.
- Limits: altitude 1-{MAX_ALTITUDE_M:.0f} m, at most {MAX_DISTANCE_FROM_HOME_M:.0f} m from home.
- If a tool returns an error, stop the mission, keep the drone safe (hover, land or return_to_launch),
  and tell the operator what went wrong, including any autopilot message.
- If you are unsure of the drone's state, call get_status first.
- When finished, reply with a short summary of what the drone did and where it is now.
- Only use the tools listed. Never invent tool results."""
