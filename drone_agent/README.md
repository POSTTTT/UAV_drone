# Drone Agent: control the simulated drone with a local LLM

An LLM agent that flies the ArduPilot SITL + Gazebo quadcopter.

You type an instruction such as *"take off to 10 m, fly 20 m north, then land"*. The model turns it into tool calls, and the tools send MAVLink commands to the drone.

The agent uses the **OpenAI-compatible chat API** with tool calling, so it works with:
- **Ollama** (default)
- LM Studio
- llama.cpp server
- vLLM
- hosted providers (Groq, OpenRouter, ...)

No code changes are needed to switch between them.

```
 Mac host (192.168.64.1)                     Ubuntu VM (192.168.64.6)
┌──────────────────────┐   HTTP :11434   ┌───────────────────────────────────────────────┐
│ Ollama  (qwen3:8b)   │◄───────────────►│ agent.py ─► tools.py ─► vehicle.py (pymavlink) │
└──────────────────────┘  tool calling   │                              │ tcp:127.0.0.1:5762
                                         │                              ▼                 │
                                         │        ArduPilot SITL ◄──► Gazebo              │
                                         │        (MAVProxy :5760, QGroundControl :14550) │
                                         └───────────────────────────────────────────────┘
```

The agent uses SITL's **spare** MAVLink port (5762), so MAVProxy and QGroundControl keep working at the same time.

## Files

| File | Purpose |
|---|---|
| `agent.py` | Chat loop: sends instructions and tool results to the LLM, runs the tools it asks for |
| `tools.py` | Tool functions, JSON schemas, safety limits, system prompt (no LLM dependency) |
| `vehicle.py` | pymavlink wrapper: connection, state cache, mode/arm/takeoff/goto/land |
| `test_vehicle.py` | Flies a short mission **without** any LLM, to check the drone link |
| `requirements.txt` | Python dependencies (`openai` client library, `pymavlink`) |

## Tools the model can call

| Tool | What it does |
|---|---|
| `get_status` | Mode, armed, altitude, position, distance from home, speed, GPS, battery, recent autopilot messages |
| `set_mode` | Change flight mode (GUIDED, LOITER, BRAKE, LAND, RTL, ...) |
| `arm` / `disarm` | Arm in GUIDED mode / disarm (refused while in the air) |
| `takeoff` | Arm if needed, climb to an altitude, wait until reached |
| `fly_relative` | Fly N/E metres from the current position, wait for arrival |
| `fly_to_location` | Fly to a lat/lon, wait for arrival |
| `hover` | Hold position for N seconds |
| `land` | Land here, wait until disarmed |
| `return_to_launch` | RTL: fly home, land, wait until disarmed |

### Safety

These checks are enforced in code (`tools.py`), whatever the model asks for:
- Altitude must be 1–50 m.
- Targets more than 300 m from home are refused.
- The drone won't disarm in the air, and it won't fly to a point unless it's airborne.

Bad tool calls come back to the model as error messages instead of crashing the agent:
- unknown tool names
- missing arguments
- invalid JSON
- numbers sent as strings (these are converted automatically)

Each instruction is capped at 25 tool calls, in case a model gets stuck in a loop.

---

## Setup

### 1. Ollama on the Mac host (one time)

On the **Mac**:

1. Install Ollama from <https://ollama.com/download> (or `brew install ollama`).
2. Download a model that supports tool calling:

   ```bash
   ollama pull qwen3:8b        # ~5 GB, good tool use; needs a Mac with 16 GB+ RAM
   # smaller Macs (8 GB):
   ollama pull qwen3:4b
   ```

3. Let the VM reach Ollama. By default Ollama only listens on the Mac itself.

   **Ollama app:**

   ```bash
   launchctl setenv OLLAMA_HOST "0.0.0.0:11434"
   ```

   Then quit Ollama from the menu bar and open it again.

   **Command line instead:**

   ```bash
   OLLAMA_HOST=0.0.0.0:11434 ollama serve
   ```

   If macOS asks whether Ollama may accept incoming network connections, click **Allow**.

4. Check it from the **VM**:

   ```bash
   curl http://192.168.64.1:11434/api/tags
   ```

   It should list the model you pulled. `192.168.64.1` is the Mac's address as seen from this VM. If it changes, check with `ip route` (the "default via" address).

### 2. Python environment in the VM (already done)

```bash
cd ~/UAV_drone
python3 -m venv .venv
.venv/bin/pip install -r drone_agent/requirements.txt
```

---

## Run

1. **Start the simulator** as described in [`simulation-guide.md`](../simulation-guide.md):
   - Gazebo with `-r`
   - SITL with the two `--add-param-file` options

   Wait for `EKF3 IMU0 is using GPS`.

2. **Optional: check the drone link without an LLM.** This flies a short mission:

   ```bash
   cd ~/UAV_drone/drone_agent
   ../.venv/bin/python test_vehicle.py
   ```

3. **Start the agent:**

   ```bash
   cd ~/UAV_drone/drone_agent
   ../.venv/bin/python agent.py
   ```

   Then type instructions:

   ```
   You: what's the drone status?
   You: take off to 10 meters
   You: fly 20 m north, then 20 m east
   You: hover for 5 seconds, then return to launch
   ```

   Or run a single instruction:

   ```bash
   ../.venv/bin/python agent.py "take off to 5 m, fly 10 m north and land"
   ```

   Type `quit` or press `Ctrl+C` to exit.

### Options

| Option | Env variable | Default |
|---|---|---|
| `--model` | `LLM_MODEL` | `qwen3:8b` |
| `--base-url` | `LLM_BASE_URL` | `http://192.168.64.1:11434/v1` (Ollama on the Mac) |
| `--api-key` | `LLM_API_KEY` | `ollama` (ignored by Ollama) |
| `--connect` | | `tcp:127.0.0.1:5762` (SITL spare MAVLink port) |

### Other backends

```bash
# Ollama inside the VM (small CPU-only model; slow, and tight on 3.8 GB RAM)
../.venv/bin/python agent.py --base-url http://localhost:11434/v1 --model qwen3:1.7b

# LM Studio on the Mac (enable "Serve on Local Network" in LM Studio)
../.venv/bin/python agent.py --base-url http://192.168.64.1:1234/v1 --model <model-id>

# llama.cpp server (start it with --jinja so tool calling works)
../.venv/bin/python agent.py --base-url http://<host>:8080/v1 --model any

# Hosted OpenAI-compatible provider
LLM_API_KEY=... ../.venv/bin/python agent.py --base-url https://openrouter.ai/api/v1 --model <model>
```

## Choosing a model

The model **must support tool/function calling**. On Ollama, look for the "tools" tag on the model page.

| Model | Size | Notes |
|---|---|---|
| `qwen3:8b` | ~5 GB | Recommended default; reliable multi-step tool use |
| `qwen3:4b` | ~2.5 GB | For 8 GB Macs; fine for simple commands |
| `llama3.1:8b` | ~5 GB | Good alternative |
| `qwen3:14b` / `mistral-small` | 9–14 GB | Better planning for complex missions, needs 24 GB+ RAM |
| `qwen3:1.7b` | ~1.4 GB | Only if it must run inside the VM; expect mistakes |

Tips for small models:
- Give **one or two steps per instruction** ("take off to 5 m", then "fly 10 m north").
- If a model answers in text instead of calling a tool, try a bigger model.

## Notes

- **Stopping the agent does not land the drone.** If you exit mid-flight, the drone keeps its current mode. Land it from MAVProxy (`land`) or QGroundControl.
- **Adding a tool:**
  1. Add a method to `DroneTools` in `tools.py`.
  2. Add a matching `_function(...)` schema to `TOOL_SCHEMAS`. The method name and argument names must match the schema.
- The first request after starting Ollama is slow while the model loads into memory.
