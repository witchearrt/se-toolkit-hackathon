#!/bin/bash
set -e

echo "🔧 Running database migration..."
python migrate.py

echo "🤖 Starting bot..."
exec python bot.py
