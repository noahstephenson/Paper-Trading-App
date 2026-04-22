#!/usr/bin/env bash
set -o errexit   # exit immediately if any command fails

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate
