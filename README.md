# abiko-tennis-watch

我孫子市民体育館テニスコート（A〜E）の**日曜 12:00〜16:00 に連続2時間以上の空き**を監視し、新しく空きが出たら通知する。

- ちば施設予約システムをログインなしで閲覧（曜日指定=日で直近7週分の日曜を取得）
- 既に通知した枠は `state.json` で記録し、新規分だけ通知
- 通知先：ntfy / Discord / LINE（`.env` で設定）

## セットアップ（Linux）

```bash
git clone <this repo> ~/abiko-tennis-watch && cd ~/abiko-tennis-watch
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install --with-deps chromium
cp .env.example .env   # 通知先を設定
.venv/bin/python tennis_watch.py   # 手動で1回動作確認
```

## 定期実行（cron）

1日4回（8/12/17/21時ごろ）。サイトに負荷をかけないよう頻度は控えめに。

```cron
CRON_TZ=Asia/Tokyo
7 8,12,17,21 * * * cd $HOME/abiko-tennis-watch && .venv/bin/python tennis_watch.py >> watch.log 2>&1
```

## メモ
- 予約自体はしない。通知を見て本人がログインして予約する
- メンテナンス中などで失敗したときは通知せず `watch.log` にエラーを残す
