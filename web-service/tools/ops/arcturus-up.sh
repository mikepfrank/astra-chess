#!/bin/sh
# Lightsail entrypoint; use ec2-user existing sudo access.
set -eu
exec sudo -n /usr/bin/python3 -I -B /home/or-chess/astra-chess/web-service/tools/ops/arcturus_service.py up "$@"
