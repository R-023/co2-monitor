#!/bin/bash
# Установка libpq-dev через apt (Render поддерживает это)
apt-get update && apt-get install -y libpq-dev
pip install -r requirements.txt