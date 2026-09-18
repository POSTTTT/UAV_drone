# UAV_drone

A simulated quadcopter that you fly with plain-English instructions sent to a local LLM.

The simulator is ArduPilot SITL, Gazebo Harmonic and QGroundControl. The agent in `drone_agent/` sends your instructions to an OpenAI-compatible model (Ollama by default). The model decides which flight tools to call, and the tools send MAVLink commands to the drone.

```
You ─► drone_agent (LLM + tools) ─► MAVLink tcp:5762 ─► ArduPilot SITL ◄─► Gazebo (Iris quadcopter)
                                                              │
                                                              └─► QGroundControl (UDP 14550)
```

## Repository layout

| Path | What it is |
|---|---|
| [`installation-guide.md`](installation-guide.md) | One-time setup: Gazebo, ArduPilot plugin, ArduPilot SITL, QGroundControl |
| [`simulation-guide.md`](simulation-guide.md) | Starting, flying and stopping the simulator, plus troubleshooting |
| [`drone_agent/`](drone_agent/) | LLM agent that flies the drone ([README](drone_agent/README.md)) |

## Requirements

- Ubuntu 24.04 (x86_64 or aarch64), at least 10 GB free disk space, and `sudo` access
- Python 3.12
- An OpenAI-compatible LLM server whose model supports tool calling. The default is Ollama with `qwen3:8b`, running on the host machine.

## Setup

1. **Simulator:** follow [`installation-guide.md`](installation-guide.md) once. When it is done, the full test (drone takes off to 5 m) should pass.
2. **LLM:** set up Ollama as described in [`drone_agent/README.md`](drone_agent/README.md#1-ollama-on-the-mac-host-one-time).
3. **Python environment for the agent:**

   ```bash
   git clone https://github.com/POSTTTT/UAV_drone.git ~/UAV_drone
   cd ~/UAV_drone
   python3 -m venv .venv
   .venv/bin/pip install -r drone_agent/requirements.txt
   ```

## Quick start

Terminal 1: start Gazebo.

```bash
gz sim -v4 -r iris_runway.sdf
```

Terminal 2: start ArduPilot SITL.

```bash
cd ~/ardupilot
source ~/venv-ardupilot/bin/activate
./Tools/autotest/sim_vehicle.py -v ArduCopter -f gazebo-iris --model JSON \
  --add-param-file=Tools/autotest/default_params/copter.parm \
  --add-param-file=Tools/autotest/default_params/gazebo-iris.parm \
  --console --map
```

Wait until the console shows `EKF3 IMU0 is using GPS`.

Terminal 3: start the agent.

```bash
cd ~/UAV_drone/drone_agent
../.venv/bin/python agent.py "take off to 5 m, fly 10 m north and land"
```

To follow the flight in QGroundControl, open `~/Downloads/QGroundControl-*.AppImage`.

To fly a real Cube Orange+ through a telemetry radio instead of SITL, add `--radio`. Read [Real drone: Cube Orange+ over a telemetry radio](drone_agent/README.md#real-drone-cube-orange-over-a-telemetry-radio) first.

> Keep both `--add-param-file` options. Without them, the drone does not arm and reports `PreArm: Motors: Check frame class and type`. See [`simulation-guide.md`](simulation-guide.md#troubleshooting).

## Safety note

The agent limits altitude to 1–50 m and refuses targets more than 300 m from home. If you stop the agent during a flight, the drone does **not** land. Land it with `land` in MAVProxy or from QGroundControl.
