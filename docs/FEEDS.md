# Connecting the data feeds

Edgewise needs three services. Each gives you a **key**: a long password for programs.
You put the keys in a settings file on the computer that runs Edgewise, restart it, and
the dashboard shows each feed as working.

The keys only ever go in that settings file. Don't paste them anywhere else, including
chats.

You can add them one at a time. Start with API-Football: Edgewise needs the list of
matches before it can match prices to them.

## 1. Fixtures and results: API-Football

1. Create a free account at **https://dashboard.api-football.com/register**.
2. Sign in. The dashboard shows your **API key**. Copy it.

The free plan allows 100 requests a day. Edgewise uses about 20 to 50.

## 2. Bookmaker odds: The Odds API

1. Go to **https://the-odds-api.com** and choose a plan. The free plan is enough to check
   that everything works, but it runs out after a few hours of scanning.
2. The key arrives by email.

Each scan of one league costs 3 credits. With all five leagues, expect roughly 70,000
credits a month, which means their 100,000-credit plan (about US$59 a month at the prices
listed online; check their pricing page). To use fewer, leave leagues out: ask Claude.

## 3. Betfair Exchange prices

1. Open a Betfair Australia account at **https://www.betfair.com.au** and complete the
   identity check.
2. Create an application key with Betfair's guide for Australian customers:
   **https://betfair-datascientists.github.io/api/apiappkey/**. It gives you two keys.
   Start with the **delayed** one (free).
3. Edgewise also needs your Betfair username and password, to log in and read prices. It
   never places bets in Phase 1.

With the delayed key, Betfair's prices can be a few minutes old, so Edgewise treats them
as too old to use in the last hour before kick-off. The live key removes that limit
(Betfair may charge a one-off fee for it).

## 4. Put the keys in the settings file

**On your laptop**, open a terminal in the betmodel folder (see `docs/LAPTOP.md`, step 3):

- **Windows (PowerShell):** run `notepad .env`. If it asks to create a new file, click
  **Yes**.
- **Mac (Terminal):** run `nano .env`.

Paste these lines, replacing everything after each `=` with your own details:

```
FOOTBALL_DATA_API_KEY=paste-your-api-football-key
ODDS_API_KEY=paste-your-odds-api-key
BETFAIR_APP_KEY=paste-your-betfair-delayed-key
BETFAIR_USERNAME=your-betfair-username
BETFAIR_PASSWORD=your-betfair-password
```

If your Betfair password contains `$`, `#`, a quote or a space, put it in single quotes,
like `BETFAIR_PASSWORD='my#pass word'`.

Save: in Notepad press **Ctrl+S** and close it; in nano press **Ctrl+O**, **Enter**, then
**Ctrl+X**. Then restart Edgewise:

```bash
docker compose up -d --build
```

**On a server**, the lines are already in `.env`. Fill them in with `nano .env`, then run
`infra/stack live up -d --build`.

## 5. Check it works

Open the dashboard and look at **System**. Within a minute or two, each feed you added
shows **Updated** with a time. Matches for the next 7 days arrive first, then their
prices.

If a feed shows **Paused**, the **Recent notices** card says why, for example "the key or
login was refused". Fix that line in `.env` and run `docker compose up -d` again.

Once all three are working, Edgewise looks for value every minute. Each value bet
appears on the dashboard under **Awaiting approval** and in **Recent notices**. Alerts to
your phone come in the next milestone.
