# ROS 2 Lyrical and Space ROS workflow

The host runs Ubuntu 26.04, so its native ROS distribution is ROS 2 Lyrical.
Space ROS is the NASA/Blue Origin project; it runs in its own development image
to keep its dependencies apart from the host. The two environments have
separate workspaces and should not share build or install directories.

After the core bootstrap, `bash scripts/phase9-ros.sh` installs the official
ROS apt source, `ros-lyrical-desktop`, and development tools. It creates
`~/Workspaces/ros2_lyrical/src`, `~/Workspaces/space_ros/src`, and two helpers
in `~/Scripts`. It pulls `osrf/space-ros:jazzy-2026.07.0-dev` if Docker is working. The image
is several GB, so retain it only while Space ROS work is active.

For native work, open a fresh terminal and run:

```bash
source ~/Scripts/ros-lyrical-env.sh
cd ~/Workspaces/ros2_lyrical
colcon build --symlink-install
source install/setup.bash  # use setup.zsh from zsh
colcon test
colcon test-result --verbose
```

Put source repositories under `src/`. Run `rosdep install --from-paths src
--ignore-src -r -y` before building when package dependencies change. Use
`ros2 doctor --report` to inspect the environment. Keep ROS activation explicit
per terminal; it is intentionally absent from the global shell startup file.

For Space ROS, run `~/Scripts/space-ros-shell.sh`. The helper uses the official
development image and mounts only `~/Workspaces/space_ros`. It uses Docker's
bridge network for dependency downloads without publishing host ports. Inside
the container, verify
`ros2 --help` and `colcon --help`; use the project's pinned `spaceros.repos`
manifest when reproducing a Space ROS build.

Do not source Lyrical and Space ROS setup files in the same shell. Do not copy
`build/`, `install/`, or `log/` between their workspaces. Back up source and
configuration, rather than compiled outputs.

Sources: [ROS Lyrical on Ubuntu](https://github.com/ros2/ros2_documentation/blob/rolling/source/Get-Started/Installation/Ubuntu-Install-Debs.rst),
[ROS supported platforms](https://github.com/ros2/ros2_documentation/blob/rolling/source/Get-Started/Releases/lyrical/supported-platforms.rst),
[Space ROS development image](https://github.com/space-ros/space-ros/blob/main/docs/USAGE.md).
