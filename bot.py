import os, re, json, random, hashlib
import datetime as dt
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw

import tweepy
from openai import OpenAI

# ========= AI (GitHub Models) =========
ai = OpenAI(
    base_url="https://models.github.ai/inference",
    api_key=os.environ["GITHUB_TOKEN"],
)

# ========= X Auth (OAuth 1.0a) =========
auth = tweepy.OAuth1UserHandler(
    consumer_key=os.environ["X_API_KEY"],
    consumer_secret=os.environ["X_API_SECRET"],
    access_token=os.environ["X_ACCESS_TOKEN"],
    access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
)
x_api_v1 = tweepy.API(auth)  # media upload
x_client_v2 = tweepy.Client(
    consumer_key=os.environ["X_API_KEY"],
    consumer_secret=os.environ["X_API_SECRET"],
    access_token=os.environ["X_ACCESS_TOKEN"],
    access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
)

HEADERS = {"User-Agent": "Mozilla/5.0 (crypto-bot)"}

COINGECKO_NEW_API = "https://api.coingecko.com/api/v3/coins/list/new"
COINGECKO_NEW_WEB = "https://www.coingecko.com/en/new-cryptocurrencies"
CRYPTORANK_UPCOMING = "https://cryptorank.io/upcoming-ico"

STATE_PATH = "state.json"
SEEN_DAYS_PROJECT = 7
SEEN_DAYS_TEXT = 2  # aynı metin 2 gün içinde tekrar olmasın

# ----------------- State -----------------
def load_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"seen_projects": {}, "seen_text_hashes": {}, "last_reply_date": ""}

def save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def iso_today():
    return dt.datetime.utcnow().date().isoformat()

def days_ago(iso_date: str) -> int:
    try:
        d = dt.date.fromisoformat(iso_date)
        return (dt.datetime.utcnow().date() - d).days
    except Exception:
        return 9999

def hash_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]

# ----------------- Helpers -----------------
def fetch_text(url: str, limit: int = 120000) -> str:
    try:
        r = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
        if r.status_code >= 400:
            return ""
        return r.text[:limit]
    except Exception:
        return ""

def pick_source_for_this_run() -> str:
    # deterministik: 07 & 15 UTC => CoinGecko; 11 & 19 UTC => CryptoRank
    h = dt.datetime.utcnow().hour
    return "coingecko" if h in (7, 15) else "cryptorank"

# ----------------- Sources -----------------
def coingecko_new_projects():
    # API dene
    try:
        r = requests.get(COINGECKO_NEW_API, headers=HEADERS, timeout=20)
        if r.status_code == 200:
            data = r.json()
            out = []
            for it in data[:80]:
                cid = it.get("id")
                name = (it.get("name") or "").strip()
                symbol = (it.get("symbol") or "").upper()
                url = f"https://www.coingecko.com/en/coins/{cid}" if cid else COINGECKO_NEW_WEB
                if name:
                    out.append({"name": name, "symbol": symbol, "url": url})
            return out
    except Exception:
        pass

    # Web fallback
    html = fetch_text(COINGECKO_NEW_WEB)
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/en/coins/" in href:
            url = "https://www.coingecko.com" + href if href.startswith("/") else href
            if url in seen:
                continue
            seen.add(url)
            name = a.get_text(" ", strip=True)
            if name and len(name) <= 40:
                out.append({"name": name, "symbol": "", "url": url})
    return out[:40]

def cryptorank_upcoming_projects():
    html = fetch_text(CRYPTORANK_UPCOMING)
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        txt = a.get_text(" ", strip=True)
        if not txt or len(txt) > 50:
            continue
        href = a["href"]
        url = "https://cryptorank.io" + href if href.startswith("/") else href
        if url in seen:
            continue
        seen.add(url)
        if "/price/" in url or "/coins/" in url or "/ico/" in url:
            out.append({"name": txt, "symbol": "", "url": url})
    return out[:40]

def find_x_handle_from_page(url: str):
    html = fetch_text(url, limit=120000)
    if not html:
        return None
    m = re.search(r"(?:x\.com|twitter\.com)/([A-Za-z0-9_]{1,15})", html)
    if not m:
        return None
    handle = m.group(1)
    if handle.lower() in {"share", "intent", "home"}:
        return None
    return "@" + handle

# ----------------- AI -----------------
def ai_research_tweet(project, source_name):
    name = project.get("name", "").strip()
    symbol = project.get("symbol", "").strip()
    url = project.get("url", "").strip()
    handle = find_x_handle_from_page(url) if url else None

    prompt = f"""
You are a friendly crypto Twitter researcher.

Write ONE tweet in Turkish with a warm, sympathetic tone (not cringe).
No emojis, no hashtags.

The tweet MUST follow this exact 3-line format:

Line 1: Mini summary (what it is / why it matters)
Line 2: Mini summary (what to watch next / potential catalyst)
Line 3: Risk: <one honest risk note>

Rules:
- Total length <= 240 characters.
- Include the URL exactly once.
- If handle is provided, include it exactly once.
- If handle is empty, DO NOT invent tags.
- Be factual. If unclear, say "net değil" or "belirsiz".

Project: {name}
Symbol: {symbol}
URL: {url}
Handle: {handle or "none"}

Return STRICT JSON:
{{"tweet":"...","caption":"..."}}
"""

    res = ai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.65,
    )

    raw = res.choices[0].message.content.strip()

    try:
        obj = json.loads(raw)
        tweet = obj.get("tweet", "").strip()[:240]
        caption = obj.get("caption", "").strip()[:70]
        return tweet, caption
    except Exception:
        fallback = f"{name}\nTakip: {url}\nRisk: erken aşama / detaylar net değil"
        return fallback[:240], name[:70]

# ----------------- Image (free, local) -----------------
def make_card(title: str, subtitle: str, out="card.png"):
    img = Image.new("RGB", (1024, 1024), color=(15, 15, 18))
    d = ImageDraw.Draw(img)
    title = title.strip()[:60]
    subtitle = subtitle.strip()[:120]
    d.text((64, 140), title, fill=(235, 235, 235))
    d.text((64, 230), subtitle, fill=(190, 190, 190))
    d.text((64, 920), "new / upcoming project", fill=(120, 120, 120))
    img.save(out, "PNG")
    return out

def post_tweet(text: str, image_path=None):
    if image_path:
        media = x_api_v1.media_upload(image_path)
        x_client_v2.create_tweet(text=text, media_ids=[media.media_id_string])
    else:
        x_client_v2.create_tweet(text=text)

# ----------------- Filters -----------------
def filter_projects(projects, state):
    today = iso_today()
    out = []
    for p in projects:
        url = p.get("url") or ""
        if not url:
            continue
        last = state["seen_projects"].get(url, "")
        if last and days_ago(last) < SEEN_DAYS_PROJECT:
            continue
        out.append(p)
    # fallback: hepsi elendiyse boş dönmeyelim
    return out or projects

def is_duplicate_text(text: str, state):
    h = hash_text(text)
    last = state["seen_text_hashes"].get(h, "")
    return bool(last and days_ago(last) < SEEN_DAYS_TEXT)

def remember_text(text: str, state):
    h = hash_text(text)
    state["seen_text_hashes"][h] = iso_today()

def remember_project(url: str, state):
    state["seen_projects"][url] = iso_today()

# ----------------- Optional Reply (safe) -----------------
def maybe_reply_once_per_day(state, reply_text: str):
    # güvenli: günde 1 reply (istersen aç)
    today = iso_today()
    if state.get("last_reply_date") == today:
        return

    # İstersen hedefi değiştirirsin
    target = "VitalikButerin"
    try:
        user = x_client_v2.get_user(username=target)
        tweets = x_client_v2.get_users_tweets(id=user.data.id, max_results=5)
        if tweets.data:
            parent_id = tweets.data[0].id
            x_client_v2.create_tweet(text=reply_text[:200], in_reply_to_tweet_id=parent_id)
            state["last_reply_date"] = today
    except Exception:
        # reply başarısızsa sessiz geç
        pass

def main():
    state = load_state()

    source = pick_source_for_this_run()
    if source == "coingecko":
        projects = coingecko_new_projects()
        source_name = "CoinGecko recently added"
    else:
        projects = cryptorank_upcoming_projects()
        source_name = "CryptoRank upcoming token sales"

    if not projects:
        # veri yoksa tweet atmayalım (noise)
        save_state(state)
        return

    candidates = filter_projects(projects, state)
    project = random.choice(candidates)

    tweet, caption = ai_research_tweet(project, source_name)
    # 3 satır garanti (main içinde)
    lines = [l.strip() for l in tweet.split("\n") if l.strip()]
    lines = lines[:3]
    while len(lines) < 3:
        if len(lines) == 2:
            lines.append("Risk: detaylar net değil / erken aşama")
        else:
            lines.append("Takip: " + (project.get("url","") or ""))
    tweet = "\n".join(lines)[:240]


    # duplicate tweet engeli
    if is_duplicate_text(tweet, state):
        project = random.choice(candidates)
        tweet, caption = ai_research_tweet(project, source_name)


    # Görsel: günde 4 run -> sadece 1’inde görsel (UTC saate bağlı deterministik)
    h = dt.datetime.utcnow().hour
    with_image = (h == 7)  # sadece TR 10:00 run’ında görsel

    if with_image:
        img = make_card(project.get("name", "New Project"), caption or "quick research")
        post_tweet(tweet, image_path=img)
    else:
        post_tweet(tweet)

    # state güncelle
    remember_project(project.get("url", ""), state)
    remember_text(tweet, state)

    # Reply (isteğe bağlı): açmak istersen aşağıdaki satırı aktif et
    # maybe_reply_once_per_day(state, "Solid point. The missing piece is market structure and incentives.")

    save_state(state)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        print("BOT FAILED:", str(e))
        traceback.print_exc()
        raise
