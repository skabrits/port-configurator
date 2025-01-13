#!/bin/bash

python main.py &
gunicorn --bind 0.0.0.0:443 --certfile=/certs/tls.crt --keyfile=/certs/tls.key "validator:app"