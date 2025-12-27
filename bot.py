import os
import re
import random
import datetime as dt
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont

import tweepy
from openai import OpenAI

# =========================
# AI (GitHub Models - FREE)
# =========================
ai = OpenAI(
    base_url="https://models.github.ai/inference",
    api_key=os.environ["GITHUB_TOKEN"],
)

# =========================
# X Auth (OAuth 1.0a)
# - Media upload için v1.1 API (tweepy.API)
# - Tweet create için v2 Client (tweepy.Client)
# =========================
auth = tweepy.OAuth1UserHandler(
    consumer_key=os.environ["X_API_KEY"],
    consumer_secret=os.environ["X_API_SECRET"],
    access_token=os.environ["X_ACCESS_TOKEN"],
    access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
)
x_api_v1 = tweepy.API(auth)

x_client_v2 = tweepy.Client(
    consumer_key=os.environ["X_API_KEY"],
    consumer_secret=os.environ["X_API_SECRET"],
    access_token=os.environ["X_ACCESS_TOKEN"],
    access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
)

HEADERS = {"User-Agent": "Mozilla/5.0 (crypto-bot)"}

# -------------------------
# Sources
# -------------------------
COINGECKO_NEW_API = "https://api.coingecko.com/api/v3/coins/list/new"  # docs exist (may be rate-limited)
COINGECKO_NEW_WEB = "https://www.coingecko.com/en/new-cryptocurrencies"  # web fallback :contentReference[oaicite:2]{index=2}
CRYPTORANK_UPCOMING = "https://cryptorank.io/upcoming-ico"  # :contentReference[oaicite:3]{index=3}


def fetch_text(url: str, limit: int = 8000) -> str:
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        return r.text[:limit]
    except Exception:
        return ""


def pick_source_for_this_run() -> str:
    """
    Günde 4 run: 2 tanesi CoinGecko, 2 tanesi CryptoRank.
    Saat bazlı deterministik: aynı gün aynı saat aynı kaynak -> daha stabil.
    """
    utc_hour = dt.datetime.utcnow().hour
    return "coingecko" if utc_hour in (7, 15) else "cryptorank"


def coingecko_new_projects() -> list[dict]:
    # 1) API dene (ücretsiz çalışırsa en temiz)
    try:
        r = requests.get(COINGECKO_NEW_API, headers=HEADERS, timeout=20)
        if r.status_code == 200:
            data = r.json()  # [{id, symbol, name, activated_at}, ...]
            out = []
            for it in data[:50]:
                cid = it.get("id")
                name = it.get("name") or ""
                symbol = (it.get("symbol") or "").upper()
                # CoinGecko coin sayfası
                url = f"https://www.coingecko.com/en/coins/{cid}" if cid else COINGECKO_NEW_WEB
                out.append({"name": name, "symbol": symbol, "url": url})
            return [x for x in out if x["name"]]
    except Exception:
        pass

    # 2) Web fallback: new-cryptocurrencies sayfasından isim/coin link çek :contentReference[oaicite:4]{index=4}
    html = fetch_text(COINGECKO_NEW_WEB, limit=120000)
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    candidates = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # coin sayfaları genelde /en/coins/<slug>
        if "/en/coins/" in href:
            name = a.get_text(" ", strip=True)
            if name and len(name) <= 40:
                url = "https://www.coingecko.com" + href if href.startswith("/") else href
                candidates.append({"name": name, "symbol": "", "url": url})

    # duplicate temizle
    seen = set()
    out = []
    for c in candidates:
        key = c["url"]
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out[:30]


def cryptorank_upcoming_projects() -> list[dict]:
    html = fetch_text(CRYPTORANK_UPCOMING, limit=160000)
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    # Sayfa dinamik olabildiği için linkleri geniş yakalıyoruz:
    # project linkleri genelde "/price/<name>" veya "/coins/<name>" benzeri olabiliyor.
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(" ", strip=True)
        if not text or len(text) > 50:
            continue
        if href.startswith("/"):
            url = "https://cryptorank.io" + href
        else:
            url = href
        # “upcoming-ico” sayfasında çok link var; proje linklerini kabaca filtreliyoruz
        if "/price/" in url or "/coins/" in url or "/ico/" in url:
            links.append({"name": text, "symbol": "", "url": url})

    # duplicate temizle
    seen = set()
    out = []
    for l in links:
        key = l["url"]
        if key not in seen:
            seen.add(key)
            out.append(l)

    # Çok gürültü olursa ilk 30 yeter
    return out[:30]


def find_x_handle_from_page(url: str) -> str | None:
    html = fetch_text(url, limit=120000)
    if not html:
        return None
    # x.com/<handle> veya twitter.com/<handle>
    m = re.search(r"(?:x\.com|twitter\.com)/([A-Za-z0-9_]{1,15})", html)
    if not m:
        return None
    handle = m.group(1)
    # Bazı sayfalarda "share" vs çıkabilir; kaba blacklist
    if handle.lower() in {"share", "intent", "home"}:
        return None
    return "@" + handle


def ai_research_tweet(project: dict, source_name: str) -> dict:
    """
    returns: {"tweet": "...", "image_caption": "..."}  (caption: görsel için kısa özet)
    """
    name = project.get("name", "").strip()
    symbol = project.get("symbol", "").strip()
    url = project.get("url", "").strip()

    handle = find_x_handle_from_page(url) if url else None

    prompt = f"""
You are a crypto Twitter researcher account.

Create ONE tweet about a NEW or UPCOMING project.
Source type: {source_name}
Project name: {name}
Symbol (may be empty): {symbol}
Source URL: {url}
Official X handle (may be empty): {handle or ""}

Rules:
- If handle is provided, include it EXACTLY ONCE.
- If handle is empty, do NOT invent tags.
- Mention the URL once.
- Add 1 risk note without accusing (e.g., 'early', 'unclear tokenomics', 'low liquidity').
- No emojis, no hashtags.
- Max 240 chars.

Also output a very short image caption (<=80 chars) summarizing the key angle.

Return STRICT JSON:
{{"tweet":"...","image_caption":"..."}}
"""
    res = ai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.6,
    )
    text = res.choices[0].message.content.strip()

    import json
    try:
        obj = json.loads(text)
        tweet = (obj.get("tweet") or "").strip()
        cap = (obj.get("image_caption") or "").strip()
        return {"tweet": tweet[:240], "image_caption": cap[:80]}
    except Exception:
        # fallback
        return {"tweet": f"{name} — early project. Source: {url}".strip()[:240], "image_caption": name[:80]}


def make_simple_image(title: str, subtitle: str, out_path: str = "card.png") -> str:
    # Basit 1024x1024 kart: ücretsiz, yerelde üretilir
    img = Image.new("RGB", (1024, 1024), color=(15, 15, 18))
    d = ImageDraw.Draw(img)

    # Font: GitHub runner’da default font garanti değil -> PIL default kullanıyoruz
    # Yazıları büyük/küçük basit yerleştiriyoruz
    title = title.strip()[:60]
    subtitle = subtitle.strip()[:120]

    d.text((64, 140), title, fill=(235, 235, 235))
    d.text((64, 220), subtitle, fill=(190, 190, 190))

    d.text((64, 900), "auto-research bot", fill=(120, 120, 120))
    img.save(out_path, "PNG")
    return out_path


def post_tweet(text: str, image_path: str | None = None):
    if image_path:
        media = x_api_v1.media_upload(image_path)  # v1.1 upload
        x_client_v2.create_tweet(text=text, media_ids=[media.media_id_string])
    else:
        x_client_v2.create_tweet(text=text)


def main():
    source = pick_source_for_this_run()

    if source == "coingecko":
        projects = coingecko_new_projects()
        source_name = "CoinGecko recently added"
    else:
        projects = cryptorank_upcoming_projects()
        source_name = "CryptoRank upcoming token sales"

    if not projects:
        # kaynaklar boşsa, güvenli fallback tweet
        post_tweet("No clean data pulled today. Skipping research post to avoid noise.")
        return

    # Rastgele 1 proje seç
    project = random.choice(projects)

    out = ai_research_tweet(project, source_name)
    tweet = out["tweet"]
    caption = out["image_caption"] or project.get("name", "New project")

    # Arada görsel: günde 4 run -> 1 tanesinde görsel (~%25)
    with_image = (random.random() < 0.25)

    if with_image:
        img_path = make_simple_image(project.get("name", "New Project"), caption)
        post_tweet(tweet, image_path=img_path)
    else:
        post_tweet(tweet)

    # (İstersen sonra açarız) Büyük hesaba reply - şimdilik kapalı tutuyorum
    # çünkü reply spam riskini artırır; önce “research feed” stabil kalsın.

if __name__ == "__main__":
    main()

