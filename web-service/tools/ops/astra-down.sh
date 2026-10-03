#!/bin/sh
# Lightsail entry point; ec2-user already has the required sudo access.
set -eu
exec sudo -n /usr/bin/python3 -I -B /home/astra/astra-chess/web-service/tools/ops/astra_service.py down "$@"
