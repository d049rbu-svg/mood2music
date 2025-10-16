import random
from typing import List, Tuple

import spotipy
from spotipy.oauth2 import SpotifyOAuth, SpotifyClientCredentials
import streamlit as st
from transformers import pipeline


# 0) ページ設定（最上部に置く）
st.set_page_config(page_title="Mood → Music (JP)", page_icon="🎵", layout="centered")

st.title("🎵 Mood → Music")
st.caption("一言日記（気分）を書くだけで、AIが感情を推定し、Spotifyから曲をおすすめします。")


# 1) サイドバー
with st.sidebar:
    st.header("設定")
    client_id = st.text_input("Spotify Client ID", type="password")
    client_secret = st.text_input("Spotify Client Secret", type="password")
    st.caption("※ https://developer.spotify.com でアプリを作成 → Client ID/Secret を取得")
    st.divider()
    st.caption("AIモデル: daigo/bert-base-japanese-sentiment（失敗時は簡易ルールにフォールバック）")
    st.caption("個人情報は保存しません。デモ用途。")


# 2) 感情モデル（関数はトップレベル = インデント無し）
@st.cache_resource(show_spinner=False)
def load_sentiment_pipeline():
    try:
        return pipeline("sentiment-analysis", model="daigo/bert-base-japanese-sentiment")
    except Exception:
        return None


def naive_sentiment(text: str) -> Tuple[str, float]:
    pos = {"嬉しい", "最高", "楽しい", "ワクワク", "感謝", "元気", "わくわく", "良い", "幸せ", "やるぞ"}
    neg = {"疲れた", "最悪", "ムカつく", "悲しい", "つらい", "無理", "だるい", "しんどい", "泣きたい", "不安", "落ち込"}
    p = sum(1 for w in pos if w in text)
    n = sum(1 for w in neg if w in text)
    if p == 0 and n == 0:
        return ("neutral", 0.5)
    label = "positive" if p >= n else "negative"
    score = 0.5 + min(0.49, abs(p - n) * 0.1)
    return (label, score)


def mood_to_queries(sent_label: str, text: str) -> List[str]:
    text_l = text.lower()
    tags: List[str] = []
    if sent_label in ("positive", "POSITIVE", "ポジティブ"):
        tags += ["happy", "energetic", "summer", "uplifting", "j-pop happy"]
    elif sent_label in ("negative", "NEGATIVE", "ネガティブ"):
        if "疲" in text or "だる" in text or "しんど" in text:
            tags += ["lofi beats", "chill", "healing piano", "relax", "study"]
        elif "悲" in text or "泣" in text or "失恋" in text:
            tags += ["sad lofi", "ballad", "piano sad", "j-pop ballad"]
        else:
            tags += ["calm", "chill", "ambient", "lofi"]
    else:
        tags += ["focus", "lofi", "coffeehouse", "chillhop"]
    if "雨" in text or "rain" in text_l:
        tags.append("rainy day")
    if "勉強" in text or "study" in text_l:
        tags.append("study lofi")
    if "朝" in text or "morning" in text_l:
        tags.append("morning")
    if "夜" in text or "night" in text_l:
        tags.append("night chill")
    seen = set()
    uniq: List[str] = []
    for t in tags:
        if t not in seen:
            uniq.append(t)
            seen.add(t)
    return uniq[:5]


def ensure_spotify(client_id: str, client_secret: str):
    """ユーザー認証の Spotipy インスタンスを作成（検索やユーザー系に利用）"""
    try:
        auth = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri="http://127.0.0.1:8501/callback/",
            scope="user-read-private,user-read-playback-state,user-read-recently-played",
            show_dialog=True,
        )
        sp_user = spotipy.Spotify(auth_manager=auth)
        sp_user.search(q="lofi", type="track", limit=1)  # 接続テスト
        return sp_user, None
    except Exception as e:
        return None, str(e)


# 3) 入力欄
text = st.text_area(
    "今日の気分を一言で（日本語OK）",
    placeholder="例）テストでミスして落ち込んだ。雨だし気分が重い…",
    height=120,
)


# 4) ボタンを押したときの処理
if st.button("おすすめを出す"):
    if not text.strip():
        st.warning("テキストを入力してね。")
        st.stop()

    # 4-1) 感情推定（ここで label/score を必ず作る）
    with st.spinner("AIが感情を分析中..."):
        clf = load_sentiment_pipeline()
        if clf is not None:
            try:
                res = clf(text[:200])  # 入力の前半200文字
                label = res[0]["label"].lower()
                score = float(res[0]["score"])
            except Exception:
                label, score = naive_sentiment(text)
        else:
            label, score = naive_sentiment(text)

        # 短文でも neutral に固定しない。キーワードがあれば強めに上書き
        positive_words = ["嬉しい", "最高", "楽しい", "ワクワク", "わくわく", "ハッピー"]
        negative_words = ["疲れ", "悲しい", "だる", "無理", "落ち込", "しんど"]
        if any(w in text for w in positive_words):
            label, score = "positive", 0.9
        elif any(w in text for w in negative_words):
            label, score = "negative", 0.9

    st.success(f"推定結果：{label}（確信度 {score:.2f}）")
    st.caption("※ モデルが落ちた場合は簡易ルール判定にフォールバックしています。")

    # 4-2) Spotify 認証チェック
    if not client_id or not client_secret:
        st.error("左のサイドバーに Spotify の Client ID / Secret を入力してください。")
        st.stop()

    sp, err = ensure_spotify(client_id, client_secret)
    if err:
        st.error(f"Spotifyエラー: {err}")
        st.stop()

    # 4-3) 検索 → ID収集
    queries = mood_to_queries(label, text)
    st.write(f"検索タグ：{', '.join(queries)}")

    results: List[dict] = []
    track_ids: List[str] = []
    artist_ids: List[str] = []

    for q in queries:
        try:
            tr = sp.search(q=q, type="track", limit=10)  # 幅を広げる
            for t in tr["tracks"]["items"]:
                results.append(
                    {
                        "id": t["id"],
                        "name": t["name"],
                        "artist": ", ".join(a["name"] for a in t["artists"]),
                        "url": t["external_urls"]["spotify"],
                        "preview_url": t.get("preview_url"),
                    }
                )
                track_ids.append(t["id"])
                if t["artists"]:
                    artist_ids.append(t["artists"][0]["id"])
        except Exception:
            pass

    # 4-4) 空チェック
    if not results or not track_ids:
        st.warning("曲が見つからなかったよ… 検索語を変えてみてください。")
        st.stop()

    # 4-5) Recommendations API（段階的フォールバック + 認証フォールバック）
    def _target_params(sent_label: str):
        if sent_label.startswith("pos"):
            return {"target_valence": 0.75, "target_energy": 0.70}
        elif sent_label.startswith("neg"):
            return {"target_valence": 0.30, "target_energy": 0.35}
        else:
            return {"target_valence": 0.50, "target_energy": 0.45}

    def _clean_ids(ids: List[str], k: int = 5) -> List[str]:
        seen = set()
        out: List[str] = []
        for x in ids:
            if x and len(x) == 22 and x not in seen:
                seen.add(x)
                out.append(x)
            if len(out) >= k:
                break
        return out

    seed_tracks = _clean_ids(track_ids)
    seed_artists = _clean_ids(artist_ids)

    # デバッグ表示（必要なければ消してOK）
    with st.expander("デバッグ: シードの中身"):
        st.write("seed_tracks:", seed_tracks[:5])
        st.write("seed_artists:", seed_artists[:5])

    reco: List[dict] = []

    # アプリ資格情報（Client Credentials）のインスタンス：ユーザー認証が失敗しても使える
    sp_app = spotipy.Spotify(
        auth_manager=SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
    )

    def _reco_with(client, **kwargs):
        try:
            return client.recommendations(**kwargs)
        except Exception:
            return {}

    try:
        params = _target_params(label)
        rec = {}

        # ① seed_tracks
        if seed_tracks:
            kwargs = dict(seed_tracks=",".join(seed_tracks[:3]), limit=30, market="JP", **params)
            rec = _reco_with(sp, **kwargs) or _reco_with(sp_app, **kwargs)

        # ② 取れなければ seed_artists
        if not rec.get("tracks") and seed_artists:
            kwargs = dict(seed_artists=",".join(seed_artists[:3]), limit=30, market="JP", **params)
            rec = _reco_with(sp, **kwargs) or _reco_with(sp_app, **kwargs)

        # ③ まだ空なら seed_genres（タグ→安全なジャンル）
        if not rec.get("tracks"):
            allow = {
                "chill",
                "ambient",
                "pop",
                "rock",
                "dance",
                "electronic",
                "hip-hop",
                "jazz",
                "classical",
                "piano",
            }
            genres: List[str] = []
            for t in queries:
                tl = t.lower()
                if "chill" in tl:
                    genres.append("chill")
                if "ambient" in tl:
                    genres.append("ambient")
                if "pop" in tl or "j-pop" in tl:
                    genres.append("pop")
                if "rock" in tl:
                    genres.append("rock")
                if "piano" in tl:
                    genres.append("piano")
            genres = [g for g in dict.fromkeys(genres) if g in allow][:3]
            if genres:
                kwargs = dict(seed_genres=",".join(genres), limit=30, market="JP", **params)
                rec = _reco_with(sp, **kwargs) or _reco_with(sp_app, **kwargs)

        if not rec.get("tracks"):
            raise Exception("Empty recommendations")

        for t in rec["tracks"]:
            reco.append(
                {
                    "id": t["id"],
                    "name": t["name"],
                    "artist": ", ".join(a["name"] for a in t["artists"]),
                    "url": t["external_urls"]["spotify"],
                    "preview_url": t.get("preview_url"),
                }
            )

    except Exception as e:
        st.warning("recommendations API での取得に失敗しました。")
        st.caption(str(e))

    # 取れたら recommendations を優先
    if reco:
        results = reco
    else:
        st.info("🎧 recommendations が取得できなかったため、検索結果からのおすすめを表示します。")

    # 4-6) 重複除去 + ランダム化でバリエーション
    uniq: List[dict] = []
    seen_keys = set()
    for r in results:
        key = (r["name"], r["artist"])
        if key not in seen_keys:
            uniq.append(r)
            seen_keys.add(key)

    random.shuffle(uniq)

    # 4-7) 表示
    st.subheader("🎧 おすすめ曲")
    for r in uniq[:15]:
        with st.container():
            st.markdown(f"**{r['name']}** — {r['artist']}  \n[Open in Spotify]({r['url']})")
            if r.get("preview_url"):
                st.audio(r["preview_url"])

