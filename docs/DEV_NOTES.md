# DEV NOTES – Crypto Twitter Bot

Internal notes for future development and maintenance.

---

## 🧠 Architecture Overview

- Scheduler: GitHub Actions (cron)
- AI: GitHub Models (OpenAI-compatible)
- Posting:
  - v2 API for tweets
  - v1.1 API for media upload
- State handling:
  - `state.json`
  - Prevents duplicate tweets and project repetition

---

## 📝 Content Logic

### Sources
- CoinGecko:
  - New / recently listed projects
- CryptoRank:
  - Upcoming token sales & launches

### Selection Rules
- Random project per run
- Skip if:
  - Posted within last 7 days
  - URL invalid or unreachable

---

## ✍️ Prompt Design Principles

- Turkish language
- Friendly, human tone
- No emojis
- No hashtags
- No hype language
- Honest uncertainty allowed:
  - “erken aşama”
  - “detaylar net değil”

### Hard Constraints
- 3 lines only
- Max 240 chars
- URL always at end of line 2
- `Risk:` always line 3

---

## 🖼️ Visuals

- Generated locally via Pillow
- Simple dark card style
- Used **once per day only**
- Avoid memes or heavy graphics (anti-spam)

---

## 🔁 Retry & Safety

- If tweet fails with 403:
  - Regenerate content once
  - Retry once
  - If still fails → skip without failing workflow

---

## 📦 State Rules

### seen_projects
- Same project not tweeted again for 7 days

### seen_text_hashes
- Same text not tweeted again for 2 days

---

## 🧩 Future Improvements (Backlog)

- Thread (weekly deep dive)
- Reply logic (1/day max, large accounts only)
- Quality scoring before posting
- Better visual templates
- Additional sources:
  - DefiLlama
  - GitHub releases
  - Project blogs / Medium
- Language A/B testing (analyst vs casual)

---

## 🏷️ Versioning

- v1.0-working → stable base
- Always tag working versions before major changes

---

## 🧠 Reminder

When returning to this project, search for:
> “Crypto Twitter bot v1.0”

This document + README are enough to resume work quickly.
