# News Digest Bot

A daily digest of 5 international news stories — AI, emerging technologies, trends and economy — curated and summarized by AI, delivered to your inbox with no server running.


## ✨ Highlights

- **Four sections in one email** - AI, emerging technologies, trends and economy, with quotas defined in `config/sections.json`
- **100% international** - the `en-US` Google News feed only; no Portuguese source anywhere in the project
- **English end to end** - headlines and summaries stay in the original language, with no translation layer between you and the story
- **No repeats across sections** - sections resolve in cascade, so an AI story never reappears under emerging technologies
- **Per-section failure isolation** - a dead feed or a bad model response drops only that section; the run fails only when every section does
- **Deduplicated** - by URL and by title similarity, plus a 7-day history that never resends what you already read
- **Ad-hoc search** - `--topic` searches a single subject and ignores the configured sections
- **Serverless** - a GitHub Actions cron job, plus manual dispatch
- **Zero credentials in code** - everything through GitHub Secrets, never written to a log
- **100% test coverage** (line and branch) with a 95% gate, without touching a real API


## 📊 What's Inside

**🤖 Artificial Intelligence** - 2 stories. Searches `artificial intelligence`

**🚀 Emerging Technologies** - 1 story. Searches `emerging technology breakthrough`

**🌍 New Trends** - 1 story. Searches `global technology trends`

**💰 Economy** - 1 story. Searches `global economy markets`, the broad macro cut — markets, central banks, inflation, global trade

Order matters. Sections are processed top to bottom and whatever one picks leaves the pool for the ones after it, so the most specific section comes first and Economy sits last, furthest from the other three.


## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12+ |
| AI | DeepSeek API (`deepseek-chat`) |
| News | Google News RSS (`feedparser`) |
| Email | Resend API |
| HTTP | httpx |
| Modeling/validation | Pydantic + pydantic-settings |
| Testing | pytest + pytest-cov |
| Automation | GitHub Actions (cron + `workflow_dispatch`) |
| Development | Built with [Claude Code](https://claude.com/claude-code) |


## 📁 Project Structure

```
news-digest-bot/
├── src/
│   ├── main.py                 # orchestration only, no business rules
│   ├── config.py               # environment-driven settings (Pydantic)
│   ├── models.py               # NewsArticle, NewsSection, SelectedNews, SentNewsRecord
│   ├── news/                   # news providers (Protocol + en-US RSS)
│   ├── services/               # sections, deduplication and digest formatting
│   ├── integrations/           # DeepSeek and Resend (HTTP only, no rules)
│   └── repositories/           # JSON history
├── config/sections.json        # digest sections (topic, emoji, quota)
├── data/sent_news.json         # stories already sent
├── tests/                      # pytest suite (95% coverage gate)
└── README.md                   # This file
```


## 🚀 Local Development

**Prerequisites:** Python 3.12+, a DeepSeek API key and a Resend API key

**Setup:**

```bash
# Clone repository
git clone <repository-url>
cd news-digest-bot

# Create the virtual environment
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate

pip install -r requirements.txt

# Configure the environment
cp .env.example .env
```

**Run:**

```bash
# Full flow: every section in config/sections.json
python -m src.main

# Ad-hoc search for a single subject (ignores the sections)
python -m src.main --topic "quantum computing"

# Print the digest without sending or writing history
python -m src.main --dry-run

# Tests
pytest
```

## 📡 Deployment

**Current Setup:** GitHub Actions, no infrastructure to maintain

**Pipeline Diagram:**

```
                          ┌─────────────────────┐
                          │  GitHub Actions     │
                          │  cron: 0 11 * * *   │
                          └──────────┬──────────┘
                                     │
                                     │ for each section, in cascade
                                     ▼
                          ┌─────────────────────┐
                          │  Google News RSS    │
                          │  (en-US feed)       │
                          └──────────┬──────────┘
                                     │
                                     │ drop duplicates, history
                                     │ and what earlier sections took
                                     ▼
                          ┌─────────────────────┐
                          │  DeepSeek API       │
                          │  (select + summary) │
                          └──────────┬──────────┘
                                     │
                                     │ one email, grouped by section
                                     ▼
                          ┌─────────────────────┐
                          │    Resend API       │
                          │  (HTML + plaintext) │
                          └──────────┬──────────┘
                                     │
                                     │ only after delivery is confirmed
                                     ▼
                          ┌─────────────────────┐
                          │  data/sent_news.json│
                          │ (committed to repo) │
                          └─────────────────────┘

Required secrets:
- DEEPSEEK_API_KEY
- RESEND_API_KEY
- EMAIL_FROM
- EMAIL_TO
```

Sections come from the versioned `config/sections.json`, so there is no topic secret.

**Schedule.** `.github/workflows/news_digest.yml` runs on `cron: "0 11 * * *"`. GitHub Actions uses **UTC**:

| Cron (UTC) | Time in America/Sao_Paulo (UTC−3) |
|------------|-----------------------------------|
| `0 11 * * *` | **08:00** |
| `0 12 * * *` | 09:00 |
| `0 21 * * *` | 18:00 |

Scheduled runs on GitHub Actions can be delayed by a few minutes at peak hours.

**Manual run.** Under **Actions → News Digest → Run workflow**, leaving `topic` empty runs the configured sections; filling it runs an ad-hoc search for that subject. `dry_run` tests without sending email.

**History persistence.** Actions runners are ephemeral, so `data/sent_news.json` is committed back to the repository (`chore: update sent news history`) — **only after email delivery is confirmed**. That is why the workflow declares `permissions: contents: write`.

`.github/workflows/tests.yml` runs `pytest` on pushes to `main` and on pull requests, sending nothing.


## 🌍 Features Explained

### Sections and the cascade
- Every entry in `config/sections.json` becomes one section of the email, in file order
- Sections resolve in cascade: the recent history plus whatever earlier sections already picked leaves the pool for the ones after
- The order is therefore a priority list — the most specific topic first, the broadest last
- Changing the mix means editing a JSON file, never touching code
- A section with no relevant news simply does not appear; the digest ships shorter and is never padded

### International-only scope
- Only the `en-US` Google News feed is queried — there is no Portuguese feed in the codebase
- Headlines and summaries stay in English, so no translation sits between the source and you
- "International" means the `en-US` feed, which can still return stories about Brazil published by English-language outlets

### Curation by AI
- DeepSeek receives up to `MAX_ARTICLES_FOR_ANALYSIS` articles per section, ordered by recency
- It groups stories covering the same event, ranks by importance and writes an 80–150 word summary for each
- Source and original headline are always taken from the article matched by URL, never from the model's response — a hallucinated outlet or headline cannot reach the email
- Each section makes its own API call, so cost and runtime scale with the number of sections

### Deduplication and history
- Duplicates are removed by URL and by title similarity (90% threshold, accent- and case-insensitive)
- A 7-day history keeps already-sent stories from coming back; records are pruned at twice the retention window
- The history stores the headline **as it came from the feed**, not what the model returned, so the comparison keeps recognizing the story on later runs
- History is written only after the email is confirmed sent — a failed delivery means the same stories can return tomorrow, which is the intended behavior

### Failure isolation
- Each section runs inside its own error boundary: a dead feed or a bad model response drops only that section
- The failure is logged at `ERROR` level with the section name and the reason
- A partial digest is still sent and the run exits `0` — the email arriving is what matters day to day
- The run exits `1` only when there is nothing to send **and** something broke, so a total failure never shows up as a green build

### Resilience
- The RSS feed and both APIs retry 3 times with exponential backoff on transport errors, `429` and `5xx`
- The feed and DeepSeek also retry on timeout; Resend deliberately does not — a timed-out send is treated as ambiguous, because the provider may already have accepted the message
- Invalid credentials (`401`/`403`) fail immediately, without burning retries
- A malformed model response is retried with an explicit instruction to return JSON only

### Email format
- Sent as HTML and plaintext, grouped by section, with the source and link for every story
- Numbering runs continuously across sections, so a five-item digest reads 1 through 5
- The date is written from a fixed month table rather than `strftime("%B")`, so it does not shift with the machine's locale

---
