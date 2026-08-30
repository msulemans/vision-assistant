#!/bin/sh
set -u

echo "architecture"
uname -m

echo "macos"
sw_vers

echo "hardware"
system_profiler SPHardwareDataType SPDisplaysDataType -detailLevel mini \
  | sed -E '/Serial Number|Hardware UUID|Provisioning UDID/d'

echo "disk"
df -h .

echo "toolchain"
for tool in python3 python3.11 git rg ffmpeg screencapture swift xcodebuild \
  llama-mtmd-cli llama-server ollama uv; do
  if command -v "$tool" >/dev/null 2>&1; then
    printf '%s\t%s\n' "$tool" "$(command -v "$tool")"
  else
    printf '%s\t%s\n' "$tool" "not found"
  fi
done

echo "project-python-packages"
python3 -m pip show mlx mlx-vlm pillow fastapi pydantic 2>/dev/null || true

echo "privacy"
echo "Screen Recording and Accessibility permission status is not requested by this script."
echo "No screenshot is captured. No local model server is contacted."
