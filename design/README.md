# Design

The full interactive preview is the claude.ai design canvas **"Edgewise Betting App"** (private to the owner).

`preview/` holds the source of each screen from that canvas, as reference for building the real web app. They are Design Component files (`.dc.html`) that render inside the canvas runtime, not standalone pages. Use them for exact layout, copy, colours and spacing.

## Screens

| File | Screen |
|---|---|
| `Main.dc.html` | Desktop · Dashboard |
| `ValueBets.dc.html` | Desktop · Value bets (approval queue) |
| `BetLog.dc.html` | Desktop · Bet log (auto-settled) |
| `Performance.dc.html` | Desktop · Model & performance |
| `Settings.dc.html` | Desktop · Settings & limits |
| `Lab.dc.html` | Desktop · Lab & releases |
| `Analyst.dc.html` | Desktop · Claude analyst |
| `PhoneToday.dc.html` | Phone · Approval queue |
| `PhoneBet.dc.html` | Phone · Bet detail |
| `PhoneLog.dc.html` | Phone · Bet log |
| `PhoneUpgrade.dc.html` | Phone · Upgrade available |

All numbers in the preview are sample data.

## Tokens

| Token | Value | Use |
|---|---|---|
| bg | `#0E1116` | Page background |
| nav | `#11161D` | Side navigation, bottom tab bar |
| surface | `#151B23` | Cards |
| surface-inset | `#121820` | Metric strips, table headers |
| border | `#232C38` | Card borders |
| divider | `#222A35` | Row dividers |
| text | `#E8EDF3` | Primary text |
| text-2 | `#C9D2DD` | Secondary text |
| muted | `#A1ACBA` | Labels |
| dim | `#8994A3` | Captions (passes 4.5:1 on surface) |
| accent | `#C6F36B` | Primary actions, edge values, awaiting approval |
| positive | `#6CC4FF` | Profit, won, positive CLV |
| negative | `#FFA466` | Loss, lost, negative CLV, warnings |
| lab | `#B9A3FF` | Placed/open bets, shadow models, Claude and lab |

Positive and negative are blue and orange (not green and red) so they stay distinguishable for colour-blind users; values also always carry a + or − sign.

Typography: IBM Plex Sans (UI), IBM Plex Mono (all numbers, odds, money). Touch targets at least 44 px.
