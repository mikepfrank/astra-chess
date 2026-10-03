#!/bin/sh
set -eu
exec sudo -n /usr/bin/python3 -I -B /home/astra/astra-chess/web-service/tools/ops/astra_service.py up "$@"
