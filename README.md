# abiko-tennis-watch

我孫子市民体育館テニスコート（A〜E）の**土日祝 12:00〜16:00 に連続1時間以上の空き**を監視し、新しく空きが出たら通知する。

- ちば施設予約システムをログインなしで閲覧（曜日指定=土・日・祝日）
- 1回の検索で7日分しか出ないため、開始日をずらして約7週先まで繰り返し検索
- 祝日判定は jpholiday で二重チェック
- 既に通知した枠は `state.json` で記録し、新規分だけ通知
- 通知先：ntfy / Discord / LINE（`.env` で設定）

## 起動（Docker / umbrel）

```bash
cp .env.example .env   # 通知先を設定
./run.sh               # イメージをビルドしてコンテナを再作成（30分ごとに実行）
```

- このフォルダを `/app` にマウントしているので、`tennis_watch.py` の変更は保存した時点で次の実行から反映される
- Dockerfile を変えたら `./run.sh` で作り直す
- 手動で1回実行：`sudo docker exec tennis-watch python /app/tennis_watch.py`

## メモ
- 予約自体はしない。通知を見て本人がログインして予約する
- メンテナンス中などで失敗したときは通知せず `watch.log` にエラーを残す
