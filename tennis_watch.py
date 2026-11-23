#!/usr/bin/env python3
"""
我孫子市民体育館テニスコート（A〜E）の土日祝の空きを監視し、
12:00〜16:00 の中で連続1時間以上空いていれば通知する。

- ちば施設予約システムをログインなしで閲覧（空き状況検索）
- 新しく見つかった空きだけ通知（state.json で既通知分を管理）
- 通知先: ntfy / Discord / LINE（.env で設定したものすべてに送る）
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

import jpholiday
from playwright.sync_api import Page, sync_playwright

BASE_URL = "https://www.cm1.eprs.jp/yoyaku-chiba/ew/index.jsp"
WINDOW_START = os.getenv("WINDOW_START", "12:00")
WINDOW_END = os.getenv("WINDOW_END", "16:00")
MIN_MINUTES = int(os.getenv("MIN_MINUTES", "60"))
STATE_FILE = Path(os.getenv("STATE_FILE", Path(__file__).with_name("state.json")))
JST = dt.timezone(dt.timedelta(hours=9))


# ---------- 空き判定（純粋関数） ----------

def to_min(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def to_hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def find_hits(slots: list[tuple[str, str]]) -> list[str]:
    """slots: [(状態, "09:00-12:00"), ...] → 条件を満たす時間帯（窓内に切り詰めたもの）"""
    ws, we = to_min(WINDOW_START), to_min(WINDOW_END)
    # 連続する「空き」をまとめる
    free: list[list[int]] = []
    for status, span in slots:
        s, e = (to_min(x) for x in span.split("-"))
        if status != "空き":
            continue
        if free and free[-1][1] == s:
            free[-1][1] = e
        else:
            free.append([s, e])
    hits = []
    for s, e in free:
        cs, ce = max(s, ws), min(e, we)
        if ce - cs >= MIN_MINUTES:
            hits.append(f"{to_hhmm(cs)}-{to_hhmm(ce)}")
    return hits

def head_to_date(head: str, today: dt.date) -> dt.date | None:
    """表の見出し（例: '11/29(土)' や '2026/11/29(土)'）を日付に変換"""
    m = re.search(r"(?:(\d{4})/)?(\d{1,2})/(\d{1,2})", head)
    if not m:
        return None
    y, mo, d = m.groups()
    mo, d = int(mo), int(d)
    year = int(y) if y else today.year + (1 if mo < today.month else 0)  # 年末年始の対応
    return dt.date(year, mo, d)


def is_target_day(d: dt.date) -> bool:
    """土日か祝日ならTrue"""
    return d.weekday() >= 5 or jpholiday.is_holiday(d)

# ---------- ブラウザ操作 ----------

def click(page: Page, js_predicate: str) -> None:
    """条件に合う <a> を探してクリックし、遷移を待つ"""
    with page.expect_navigation(wait_until="load", timeout=30_000):
        found = page.evaluate(
            f"""() => {{
                const a = [...document.querySelectorAll('a')].find(a => {{
                    const t = a.textContent.trim();
                    const h = a.getAttribute('href') || '';
                    const alts = [...a.querySelectorAll('img')].map(i => i.alt);
                    return {js_predicate};
                }});
                if (a) a.click();
                return !!a;
            }}"""
        )
        if not found:
            raise RuntimeError(f"リンクが見つかりません: {js_predicate}")


def click_text(page: Page, text: str) -> None:
    click(page, f"t === {json.dumps(text)} || alts.includes({json.dumps(text)})")


def next_sunday(today: dt.date) -> dt.date:
    return today + dt.timedelta(days=(6 - today.weekday()) % 7)


def open_sunday_view(page: Page, start: dt.date) -> None:
    page.goto(BASE_URL, wait_until="load")
    click_text(page, "施設の空き状況")
    click(page, "h.includes('InstSrchPpsdAction')")  # 利用目的から
    for label in ["屋外スポーツ", "テニス", "我孫子市", "我孫子市全域", "我孫子市民体育館", "すべて"]:
        click_text(page, label)

    # カレンダーで直近の日曜を選ぶ（月をまたぐ場合は翌月へ）
    sunday = start
    day_href = f", {sunday.year}, {sunday.month}, {sunday.day})"
    now = dt.datetime.now(JST)
    y, m = now.year, now.month
    while not page.query_selector(f"a[href*='{day_href}']"):
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)  # 翌月へ
        if (y, m) > (sunday.year, sunday.month):
            raise RuntimeError(f"カレンダーに {sunday} が見つかりません")
        click(page, f"h.includes('moveCalender') && h.includes(', {y}, {m})')")
    page.evaluate(
        f"""() => {{
            const links = [...document.querySelectorAll('a')];
            const day = links.find(a => (a.getAttribute('href')||'').includes(', {sunday.year}, {sunday.month}, {sunday.day})'));
            if (!day) throw new Error('日付リンクが見つかりません');
            day.click();
                links.filter(a => /weektype[567]/.test(a.getAttribute('href')||'')).forEach(a => a.click()); // 土日祝
        }}"""
    )
    click(page, "h.includes('sendSelectDay')")  # 検索開始


EXTRACT_JS = r"""() => {
  const inst = ([...document.querySelectorAll('a')].find(a => /市民テニス/.test(a.textContent)) || {}).textContent || '';
  const t = [...document.querySelectorAll('table')].find(t =>
      t.rows.length === 2 && /\d\d\/\d\d\(/.test(t.rows[0].textContent));
  if (!t) return null;
  const heads = [...t.rows[0].cells].map(c => c.textContent.trim());
  const days = [...t.rows[1].cells].map(cell => {
    const slots = []; let status = null;
    const walk = n => {
      for (const c of n.childNodes) {
        if (c.nodeName === 'IMG') status = c.alt;
        else if (c.nodeType === 3) {
          const m = c.textContent.match(/(\d\d:\d\d-\d\d:\d\d)/);
          if (m && status) slots.push([status, m[1]]);
        } else walk(c);
      }
    };
    walk(cell);
    return slots;
  });
  const hasNext = [...document.querySelectorAll('a img')].some(i => i.alt === '次の施設');
  return { court: inst.replace(/\s+/g, ' ').trim(), heads, days, hasNext };
}"""


def scrape(weeks: int = 7) -> list[dict]:
    results = []
    today = dt.datetime.now(JST).date()
    until = today + dt.timedelta(weeks=weeks)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="ja-JP")
        try:
            start = today
            while start < until:
                open_sunday_view(page, start)
                last = start
                while True:
                    data = page.evaluate(EXTRACT_JS)
                    if not data:
                        raise RuntimeError("空き状況の表が見つかりません")
                    court = data["court"].split(" ")[-1]
                    for head, slots in zip(data["heads"], data["days"]):
                        d = head_to_date(head, today)
                        if d is None:
                            continue
                        last = max(last, d)
                        if not is_target_day(d):
                            continue
                        for hit in find_hits([tuple(s) for s in slots]):
                            results.append({"date": head, "court": court, "time": hit})
                    if not data["hasNext"]:
                        break
                    click_text(page, "次の施設")
                start = last + dt.timedelta(days=1)  # 表の最後の日の翌日から次の検索
        finally:
            browser.close()
    return results

# ---------- 通知 ----------

def post(url: str, body: bytes, headers: dict) -> None:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    urllib.request.urlopen(req, timeout=20).read()


def notify(text: str) -> None:
    sent = False
    if url := os.getenv("NTFY_URL"):  # 例: https://ntfy.sh/your-secret-topic
        post(url, text.encode(), {"Title": "Tennis court open".encode(), "Tags": "tennis"})
        sent = True
    if url := os.getenv("DISCORD_WEBHOOK_URL"):
        post(url, json.dumps({"content": text}).encode(), {"Content-Type": "application/json"})
        sent = True
    token, to = os.getenv("LINE_CHANNEL_TOKEN"), os.getenv("LINE_TO")
    if token and to:
        post("https://api.line.me/v2/bot/message/push",
             json.dumps({"to": to, "messages": [{"type": "text", "text": text}]}).encode(),
             {"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
        sent = True
    if not sent:
        print("[notify] 通知先が未設定のため標準出力のみ\n" + text)


# ---------- main ----------

def load_env() -> None:
    env = Path(__file__).with_name(".env")
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    load_env()
    try:
        hits = scrape()
    except Exception as e:  # メンテ中など。失敗は通知せずログだけ
        print(f"[error] {e}", file=sys.stderr)
        return 1

    keys = {f"{h['date']}|{h['court']}|{h['time']}" for h in hits}
    old = set(json.loads(STATE_FILE.read_text())) if STATE_FILE.exists() else set()
    new = sorted(keys - old)
    STATE_FILE.write_text(json.dumps(sorted(keys), ensure_ascii=False))

    print(f"[{dt.datetime.now(JST):%F %R}] 該当 {len(keys)} 件 / 新規 {len(new)} 件")
    if new:
        lines = [f"・{k.replace('|', ' ')}" for k in new]
        notify("🎾 我孫子市民体育館テニスに土日祝の空きが出ました\n"
               + "\n".join(lines)
               + "\n予約はこちら（要ログイン）: " + BASE_URL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
