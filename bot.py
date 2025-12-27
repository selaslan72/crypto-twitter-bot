import os
import requests
from openai import OpenAI

# --- GitHub Models (ÜCRETSİZ) ---
# Not: GitHub Models endpoint olarak artık models.github.ai kullanın (Azure endpoint deprecated).
# Kaynak: GitHub changelog. 
# https://models.github.ai/inference OpenAI-uyumlu bir endpoint gibi kullanılabilir.
client = OpenAI(
    base_url="https://models.github.ai/inference",
    api_key=os.environ["GITHUB_TOKEN"],  # GitHub Actions otomatik verir
)

# --- X API (Tweet atma / Reply) ---
X_API_BASE = "https://api.x.com/2"
X_BEARER = os.environ.get("X_BEARER_TOKEN", "").strip()

def x_get_user_id(username: str) -> str:
    # GET /2/users/by/username/:username
    url = f"{X_API_BASE}/users/by/username/{username}"
    r = requests.get(url, headers={"Authorization": f"Bearer {X_BEARER}"}, timeout=30)
    r.raise_for_status()
    return r.json()["data"]["id"]

def x_get_latest_tweet_id(user_id: str) -> str:
    # GET /2/users/:id/tweets (son tweet)
    url = f"{X_API_BASE}/users/{user_id}/tweets"
    params = {"max_results": 5, "exclude": "retweets,replies"}
    r = requests.get(url, headers={"Authorization": f"Bearer {X_BEARER}"}, params=params, timeout=30)
    r.raise_for_status()
    tweets = r.json().get("data", [])
    if not tweets:
        return ""
    return tweets[0]["id"]

def x_post_tweet(text: str) -> str:
    # POST /2/tweets
    url = f"{X_API_BASE}/tweets"
    payload = {"text": text}
    r = requests.post(url, headers={"Authorization": f"Bearer {X_BEARER}", "Content-Type": "application/json"}, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()["data"]["id"]

def x_reply(text: str, in_reply_to_tweet_id: str) -> str:
    # POST /2/tweets with reply object
    url = f"{X_API_BASE}/tweets"
    payload = {"text": text, "reply": {"in_reply_to_tweet_id": in_reply_to_tweet_id}}
    r = requests.post(url, headers={"Authorization": f"Bearer {X_BEARER}", "Content-Type": "application/json"}, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()["data"]["id"]

def ai_generate(context: str) -> dict:
    """
    Çıktı:
      tweets: 3-4 adet
      replies: 1-2 adet (kısa)
    """
    prompt = f"""
Güncel bağlam (context) aşağıda.
Bu bağlama göre:
- 4 kısa tweet üret (max 240 karakter, insan gibi, tekrar yok).
- 2 kısa reply üret (max 200 karakter, saygılı, spam değil).

Context:
{context}

JSON formatında dön:
{{
  "tweets": ["...", "...", "...", "..."],
  "replies": ["...", "..."]
}}
"""
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    text = resp.choices[0].message.content

    # Basit parse: JSON bekliyoruz, olmazsa düz metin fallback
    import json
    try:
        return json.loads(text)
    except Exception:
        return {"tweets": [text], "replies": []}

def main():
    # Büyük hesap listesi (isteyince değiştiririz)
    targets = ["cz_binance", "VitalikButerin"]

    # Güncel context: bu hesapların son tweet ID’lerini alıp “güncel konu” gibi kullanacağız.
    # Free tier okuma limitleri düşük olduğu için HAFİF kullanıyoruz.
    context_lines = []
    for u in targets:
        uid = x_get_user_id(u)
        tid = x_get_latest_tweet_id(uid)
        if tid:
            context_lines.append(f"Target @{u} latest tweet id: {tid}")

    if not context_lines:
        context_lines = ["Crypto markets are moving fast today. Focus: liquidity, narratives, and risk management."]

    context = "\n".join(context_lines)

    ai_out = ai_generate(context)
    tweets = ai_out.get("tweets", [])[:4]
    replies = ai_out.get("replies", [])[:2]

    # 1) 3 veya 4 tweet at
    posted_tweet_ids = []
    for t in tweets[:4]:
        t = t.strip()
        if t:
            tid = x_post_tweet(t)
            posted_tweet_ids.append(tid)

    # 2) 1-2 reply at (targets'ın son tweetine)
    # Basit: ilk target'ın son tweetine reply
    if replies:
        first_target_id = x_get_user_id(targets[0])
        latest_target_tweet = x_get_latest_tweet_id(first_target_id)
        if latest_target_tweet:
            for rtxt in replies[:2]:
                rtxt = rtxt.strip()
                if rtxt:
                    x_reply(rtxt, latest_target_tweet)

if __name__ == "__main__":
    main()
