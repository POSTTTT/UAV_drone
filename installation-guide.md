# Drone Simulation: One-Time Setup

### ArduPilot SITL + Gazebo Harmonic + QGroundControl on Ubuntu 24.04

Follow this **once** on a new machine. To run the simulation afterwards, see `simulation-guide.md`.

| Component | Installed to |
|---|---|
| Gazebo Harmonic (Gazebo Sim 8) | system packages, command `gz` |
| ArduPilot Gazebo plugin | `~/gz_ws/src/ardupilot_gazebo` |
| ArduPilot SITL | `~/ardupilot` |
| ArduPilot Python venv | `~/venv-ardupilot` (created by the installer) |
| QGroundControl | `~/Downloads/QGroundControl-<arch>.AppImage` |

**Requirements:** Ubuntu 24.04 (noble), internet connection, about 10 GB free disk space, and a user with `sudo`.

Check your OS and CPU architecture:

```bash
cat /etc/os-release | grep VERSION=   # should say 24.04 (Noble Numbat)
uname -m                              # x86_64 or aarch64
```

---

## Step 1: Install Gazebo Harmonic

```bash
sudo apt update
sudo apt install -y curl gnupg lsb-release

sudo curl https://packages.osrfoundation.org/gazebo.gpg \
  -o /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/pkgs-osrf-archive-keyring.gpg] https://packages.osrfoundation.org/gazebo/ubuntu-stable $(lsb_release -cs) main" | \
  sudo tee /etc/apt/sources.list.d/gazebo-stable.list

sudo apt update
sudo apt install -y gz-harmonic
```

**Verify** (close the window with `Ctrl+C` in the terminal):

```bash
which gz            # /usr/bin/gz
gz sim --version    # Gazebo Sim, version 8.x
gz sim -v4 -r shapes.sdf
```

> Do not use the Snap `gazebo.gz` wrapper; use the native `gz` command.

---

## Step 2: Build the ArduPilot Gazebo plugin

Install the build dependencies:

```bash
sudo apt install -y git cmake g++ libgz-sim8-dev rapidjson-dev libopencv-dev \
  libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev \
  gstreamer1.0-plugins-bad gstreamer1.0-libav gstreamer1.0-gl
```

Clone and build:

```bash
mkdir -p ~/gz_ws/src
cd ~/gz_ws/src
git clone https://github.com/ArduPilot/ardupilot_gazebo.git

export GZ_VERSION=harmonic
cd ~/gz_ws/src/ardupilot_gazebo
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=RelWithDebInfo
make -j4
```

Add the environment variables to `~/.bashrc` (run this **only once**, or the lines get duplicated):

```bash
cat >> ~/.bashrc <<'EOF'

# ArduPilot Gazebo plugin
export GZ_VERSION=harmonic
export GZ_SIM_SYSTEM_PLUGIN_PATH=$HOME/gz_ws/src/ardupilot_gazebo/build:${GZ_SIM_SYSTEM_PLUGIN_PATH}
export GZ_SIM_RESOURCE_PATH=$HOME/gz_ws/src/ardupilot_gazebo/models:$HOME/gz_ws/src/ardupilot_gazebo/worlds:${GZ_SIM_RESOURCE_PATH}
EOF
source ~/.bashrc
```

**Verify:**

```bash
ls ~/gz_ws/src/ardupilot_gazebo/build/libArduPilotPlugin.so
echo $GZ_SIM_SYSTEM_PLUGIN_PATH
echo $GZ_SIM_RESOURCE_PATH
gz sim -v4 -r iris_runway.sdf     # Iris quadcopter on a runway; close with Ctrl+C
```

---

## Step 3: Install ArduPilot SITL

```bash
cd ~
git clone --recurse-submodules https://github.com/ArduPilot/ardupilot.git
cd ~/ardupilot
Tools/environment_install/install-prereqs-ubuntu.sh -y
. ~/.profile
```

The installer:
- installs the build tools and MAVProxy
- creates the Python venv `~/venv-ardupilot`
- adds the venv and `~/ardupilot/Tools/autotest` to `~/.profile`

**Log out and log back in** (or reboot) so the changes apply to every terminal.

Build ArduCopter for SITL (takes a few minutes):

```bash
cd ~/ardupilot
source ~/venv-ardupilot/bin/activate
./waf configure --board sitl
./waf copter
```

**Verify:**

```bash
ls ~/ardupilot/build/sitl/bin/arducopter
```

Optional quick test without Gazebo (close with `Ctrl+C`):

```bash
./Tools/autotest/sim_vehicle.py -v ArduCopter -f quad --console --map
```

---

## Step 4: Install QGroundControl

1. Download the AppImage for your CPU from <https://docs.qgroundcontrol.com/master/en/qgc-user-guide/getting_started/download_and_install.html>:
   - `x86_64` → `QGroundControl-x86_64.AppImage`
   - `aarch64` → `QGroundControl-aarch64.AppImage`
2. Save it to `~/Downloads`, then:

```bash
sudo usermod -aG dialout $USER                  # serial port access (for real hardware later)
sudo apt install -y gstreamer1.0-plugins-good libfuse2t64
chmod +x ~/Downloads/QGroundControl-*.AppImage
```

3. Log out and back in (for the `dialout` group change).

**Verify:**

```bash
~/Downloads/QGroundControl-*.AppImage
```

The QGroundControl window should open. The warning `Geolocation disabled for UID 1000` is harmless.

---

## Step 5: First full test

Run each part in its own terminal, in this order.

**Terminal 1:** Gazebo

```bash
gz sim -v4 -r iris_runway.sdf
```

**Terminal 2:** ArduPilot SITL

```bash
cd ~/ardupilot
source ~/venv-ardupilot/bin/activate
./Tools/autotest/sim_vehicle.py -v ArduCopter -f gazebo-iris --model JSON \
  --add-param-file=Tools/autotest/default_params/copter.parm \
  --add-param-file=Tools/autotest/default_params/gazebo-iris.parm \
  --console --map
```

> Keep both `--add-param-file` options. In current ArduPilot dev builds, `--model JSON` no longer loads the Iris defaults, and the drone refuses to arm with `PreArm: Motors: Check frame class and type`.

**Then start QGroundControl:**

```bash
~/Downloads/QGroundControl-*.AppImage
```

Wait for `EKF3 IMU0 is using GPS`, then type in Terminal 2:

```
mode guided
arm throttle
takeoff 5
```

If the drone climbs in Gazebo and QGroundControl shows it flying, the setup is complete.

---

## Setup checklist

- [ ] `gz sim --version` shows Gazebo Sim 8.x
- [ ] `gz sim -v4 -r shapes.sdf` opens a window
- [ ] `libArduPilotPlugin.so` exists in `~/gz_ws/src/ardupilot_gazebo/build`
- [ ] `GZ_SIM_SYSTEM_PLUGIN_PATH` and `GZ_SIM_RESOURCE_PATH` are set in `~/.bashrc`
- [ ] `gz sim -v4 -r iris_runway.sdf` shows the Iris drone
- [ ] `~/venv-ardupilot` exists
- [ ] `~/ardupilot/build/sitl/bin/arducopter` exists
- [ ] QGroundControl AppImage opens
- [ ] Full test: the drone takes off to 5 m

## References

- Gazebo Harmonic install: <https://gazebosim.org/docs/harmonic/install_ubuntu/>
- ArduPilot Gazebo plugin: <https://github.com/ArduPilot/ardupilot_gazebo>
- ArduPilot build environment: <https://ardupilot.org/dev/docs/building-setup-linux.html>
- ArduPilot SITL with Gazebo: <https://ardupilot.org/dev/docs/sitl-with-gazebo.html>
- QGroundControl: <https://docs.qgroundcontrol.com>
