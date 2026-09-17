# Drone Simulation Guide

### ArduPilot SITL + Gazebo Harmonic + QGroundControl

This guide matches how the simulator is actually installed on **this** computer.

| Item | Value on this machine |
|---|---|
| OS | Ubuntu 24.04 (noble), **aarch64 / ARM** |
| Container | **None.** Everything runs directly on the system (no Distrobox or podman) |
| Gazebo | Gazebo Harmonic (Gazebo Sim 8), command: `gz` |
| ArduPilot source | `~/ardupilot` (ArduCopter 4.8.0-dev) |
| Python venv | `~/venv-ardupilot` |
| Gazebo plugin | `~/gz_ws/src/ardupilot_gazebo` |
| QGroundControl | `~/Downloads/QGroundControl-aarch64.AppImage` |

```
QGroundControl  <-- MAVLink UDP 14550 -->  ArduPilot SITL (+ MAVProxy)
                                                 |
                                            JSON / UDP 9002
                                                 |
                              ardupilot_gazebo plugin  ->  Gazebo Harmonic  ->  Iris quadcopter
```

> Everything must already be installed. For first-time setup, see `installation-guide.md`.

---

## Part 1: Start the simulation (every time)

Open **two terminals** (`Ctrl+Alt+T`) and start things **in this order**.

### Terminal 1: Gazebo

```bash
gz sim -v4 -r iris_runway.sdf
```

Wait until the Gazebo window shows the Iris drone. Leave the terminal running.

### Terminal 2: ArduPilot SITL

```bash
cd ~/ardupilot
source ~/venv-ardupilot/bin/activate
./Tools/autotest/sim_vehicle.py -v ArduCopter -f gazebo-iris --model JSON \
  --add-param-file=Tools/autotest/default_params/copter.parm \
  --add-param-file=Tools/autotest/default_params/gazebo-iris.parm \
  --console --map
```

> **Important:** keep both `--add-param-file` options. Without them the drone **will not arm** (see Troubleshooting).

This opens a MAVProxy **console** window and a **map** window. Leave the terminal running.

### QGroundControl

```bash
~/Downloads/QGroundControl-aarch64.AppImage
```

You can also double-click the file in the Downloads folder. It connects to the drone automatically over UDP port 14550.

---

## Part 2: Fly the drone

1. Wait **30 to 60 seconds** after SITL starts, until the console shows:
   ```
   EKF3 IMU0 is using GPS
   ```
2. In **Terminal 2** (prompt looks like `STABILIZE>`), type these one at a time:

```
mode guided
arm throttle
takeoff 5
```

The drone climbs to about 5 m in Gazebo, and QGroundControl shows the same state.

### Useful MAVProxy commands

| Command | What it does |
|---|---|
| `mode guided` | Mode that accepts takeoff and "fly to" commands |
| `arm throttle` | Arm the motors |
| `takeoff 5` | Take off to 5 m (GUIDED mode only) |
| `guided <lat> <lon> <alt>` | Fly to a position (or right-click the map → *Fly To*) |
| `mode loiter` | Hold position |
| `mode rtl` | Return to launch and land |
| `land` | Land where it is |
| `disarm` | Disarm the motors after landing |
| `status` | Show vehicle status |
| `output` | List MAVLink outputs (QGC should use 127.0.0.1:14550) |

The drone disarms automatically a few seconds after landing. You also have about **10 seconds** after `arm throttle` to take off before it disarms itself (parameter `DISARM_DELAY`).

### Flying from QGroundControl instead

- **Takeoff** on the left toolbar → slide to confirm
- Click the map → **Go to location**
- **Land** / **RTL** on the left toolbar

---

## Part 3: Stop the simulation

1. **Terminal 2:** `Ctrl+C` (stops ArduPilot and MAVProxy)
2. **Terminal 1:** `Ctrl+C` (stops Gazebo)
3. Close QGroundControl

---

## Troubleshooting

### `PreArm: Motors: Check frame class and type` / `Frame: UNSUPPORTED`

- **Cause:** a bug in this ArduPilot dev version. With `--model JSON`, `sim_vehicle.py` no longer loads the Iris default parameters, so `FRAME_CLASS` stays `0`.
- **Fix:** start SITL with the two `--add-param-file` options exactly as in Part 1.
- **Check:** after startup the console should print `Frame: QUAD/X`.

### `PreArm: Accels inconsistent` / `Gyros inconsistent` / GPS messages

These are normal for the first few seconds. Wait for `EKF3 IMU0 is using GPS`, then arm again.

### Stuck at "Waiting for heartbeat" / "link 1 down" / drone does not move

- **Cause:** Gazebo is **paused**. ArduPilot waits for sensor data from Gazebo and never starts.
- Always start Gazebo with **`-r`**: `gz sim -v4 -r iris_runway.sdf`
- If you forgot `-r`, press the **▶ (play)** button at the bottom-left of the Gazebo window.
- Start Gazebo first, then SITL.

### "Unable to find or download file"

- Check the world name: it is `iris_runway.sdf` with an **underscore**, not `iris-runway.sdf`.
- If the name is right, run `source ~/.bashrc` (see "Iris world / plugin not found" below).

### `gz: command not found` or wrong Gazebo

```bash
which gz            # should be /usr/bin/gz
gz sim --version    # should be Gazebo Sim 8.x
```

Do not use the Snap `gazebo.gz` wrapper.

### Iris world / plugin not found

```bash
echo $GZ_SIM_RESOURCE_PATH       # must contain ~/gz_ws/src/ardupilot_gazebo/models and /worlds
echo $GZ_SIM_SYSTEM_PLUGIN_PATH  # must contain ~/gz_ws/src/ardupilot_gazebo/build
ls ~/gz_ws/src/ardupilot_gazebo/build/libArduPilotPlugin.so
```

If these are empty, run `source ~/.bashrc`.

### QGroundControl does not connect

- In the MAVProxy console type `output` and confirm `127.0.0.1:14550` is listed.
- If it is missing, type `output add 127.0.0.1:14550`.
- In QGC, check **Application Settings → Comm Links → AutoConnect → UDP** is enabled.
- The warning `Geolocation disabled for UID 1000` in QGC is harmless.

### Start fresh (reset all parameters)

Add `-w` (wipe) to the SITL command once:

```bash
./Tools/autotest/sim_vehicle.py -v ArduCopter -f gazebo-iris --model JSON -w \
  --add-param-file=Tools/autotest/default_params/copter.parm \
  --add-param-file=Tools/autotest/default_params/gazebo-iris.parm \
  --console --map
```

### Leftover processes after a crash

```bash
pgrep -af "arducopter|mavproxy|gz sim"
pkill -f build/sitl/bin/arducopter
pkill -f mavproxy.py
pkill -f "gz sim"
```

---

## References

- ArduPilot SITL with Gazebo: <https://ardupilot.org/dev/docs/sitl-with-gazebo.html>
- ArduPilot Gazebo plugin: <https://github.com/ArduPilot/ardupilot_gazebo>
- Gazebo Harmonic install: <https://gazebosim.org/docs/harmonic/install_ubuntu/>
- MAVProxy commands: <https://ardupilot.org/mavproxy/>
- QGroundControl: <https://docs.qgroundcontrol.com>
