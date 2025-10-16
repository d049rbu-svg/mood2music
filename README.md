
# Mood → Music (JP) — Streamlit

一言日記（日本語）から AI が感情を推定し、Spotify から気分に合う曲を提案するデモ。

## セットアップ
```bash
python -m venv .venv
# Windows: .\.venv\Scripts\Activate.ps1
# mac: source .venv/bin/activate
pip install -r requirements.txt
```

## Spotify 準備
- https://developer.spotify.com → Dashboard → Create app
- Client ID / Secret を取得し、アプリのサイドバーに入力

## 起動
```bash
streamlit run app.py
```
→ ブラウザ: http://localhost:8501

