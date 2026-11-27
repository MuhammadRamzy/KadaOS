#!/usr/bin/env bash
# Source this file in each ROS 2 Lyrical terminal. Do not source Space ROS here.
if [ -n "${ZSH_VERSION:-}" ]; then
  source /opt/ros/lyrical/setup.zsh
  [ ! -f "$HOME/Workspaces/ros2_lyrical/install/setup.zsh" ] || \
    source "$HOME/Workspaces/ros2_lyrical/install/setup.zsh"
else
  source /opt/ros/lyrical/setup.bash
  [ ! -f "$HOME/Workspaces/ros2_lyrical/install/setup.bash" ] || \
    source "$HOME/Workspaces/ros2_lyrical/install/setup.bash"
fi
export ROS_WORKSPACE="$HOME/Workspaces/ros2_lyrical"
