#!/bin/sh
# イメージを作り直してコンテナを再作成する（30分ごとに監視）
set -e
cd "$(dirname "$0")"
sudo docker build -t tennis-watch .
sudo docker rm -f tennis-watch 2>/dev/null || true
sudo docker run -d --name tennis-watch --restart unless-stopped \
  -v "$PWD":/app -w /app \
  tennis-watch sh -c 'while true; do python tennis_watch.py >> watch.log 2>&1; sleep 1800; done'
