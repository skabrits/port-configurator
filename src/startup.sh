#!/bin/bash

until python main.py; do echo "crashed in main.py"; sleep 1; done &
gunicorn "validator:app" --bind 0.0.0.0:443 --certfile=/certs/tls.crt --keyfile=/certs/tls.key --capture-output --access-logfile '-' --error-logfile '-'