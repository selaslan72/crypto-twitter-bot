# crypto-twitter-bot
# Crypto Twitter Bot

This repository contains an automated Twitter (X) bot focused on **new and upcoming crypto projects**.

The bot runs fully **for free** using:
- GitHub Actions (scheduler)
- GitHub Models (OpenAI-compatible)
- Public crypto data sources (CoinGecko, CryptoRank)
- X (Twitter) API via Tweepy

---

## 🚀 What This Bot Does

- Posts **3–4 tweets per day** automatically
- Focuses on:
  - Newly listed crypto projects
  - Upcoming token sales / launches
- Uses a **fixed 3-line tweet format**:
  1. Mini summary (what it is / why it matters)
  2. What to watch next + **link at the end**
  3. `Risk:` honest, short risk note
- Uses a **friendly, sympathetic tone** (not shill, not cringe)
- Optionally adds **1 visual per day**
- Avoids:
  - Duplicate tweets
  - Repeating the same project within 7 days
  - Broken or invalid links

---

## 🧠 Tweet Format Example

