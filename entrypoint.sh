#!/bin/bash
set -e
alembic upgrade head
exec gunicorn -w 1 -b 0.0.0.0:5000 app:app