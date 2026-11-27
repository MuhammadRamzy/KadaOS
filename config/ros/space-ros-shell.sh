#!/usr/bin/env bash
# Open the official Space ROS dev image with only the workspace mounted.
set -euo pipefail
workspace="$HOME/Workspaces/space_ros"
mkdir -p "$workspace/src"
docker run --rm -it \
  --network bridge \
  --security-opt no-new-privileges \
  --cap-drop ALL \
  --volume "$workspace:/workspaces/space_ros" \
  --workdir /workspaces/space_ros \
  osrf/space-ros:jazzy-2026.07.0-dev /bin/bash
