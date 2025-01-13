#!/bin/bash

python main.py &
gunicorn "validator:app" --bind 0.0.0.0:443 --certfile=/certs/tls.crt --keyfile=/certs/tls.key --capture-output --access-logfile '-' --error-logfile '-'