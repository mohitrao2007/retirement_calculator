# Retirement Calculator (Flask)

## Run it locally

```bash
cd retirement_calculator
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5000 in your browser.

## Deploy it for free on Render

This repo is ready to push as-is.

1. Push this `retirement_calculator` folder to a new GitHub repo (it needs to
   be the repo root, or point Render at this subfolder as the "Root
   Directory").
2. Go to [render.com](https://render.com), sign up (no card required), and
   click **New → Blueprint**. Point it at your repo — Render will read
   `render.yaml` and configure everything automatically (build command,
   start command, and a random `SECRET_KEY`).
   - No `render.yaml`? Click **New → Web Service** instead and set:
     - Build Command: `pip install -r requirements.txt`
     - Start Command: `gunicorn app:app`
     - Plan: **Free**
3. Click **Deploy**. Render gives you a `https://<your-app>.onrender.com`
   URL once the build finishes (a couple of minutes).

Free-tier notes: the app sleeps after ~15 minutes of no traffic and takes a
few seconds to wake up on the next visit, but stays deployed indefinitely at
no cost. No database is used, so there's nothing else to provision.

**About the secret key.** The app ships with a fixed, already-generated
`SECRET_KEY` fallback baked into `app.py`, so it works out of the box even if
you don't set anything in Render. If you deploy via the Blueprint
(`render.yaml`), Render instead generates and injects its own random
`SECRET_KEY` environment variable, which takes precedence — that's the
recommended setup. Either way, nothing sensitive is ever stored in the
session (just the form values you typed in, held server-side for as long as
your browser session lasts), so this doesn't affect what the app does, only
who could theoretically forge that cookie.

## What it calculates

**Accumulation phase (current age → retirement age).** Each investment bucket
you enter (Mutual Funds, Shares, Commodities, LIC/NPS/EPF, Other) is compounded
every year starting at your current age, forward to your retirement age, at
its own expected growth rate. The results page shows this year by year, not
just the final total.

**Decumulation phase (retirement age → life expectancy, default 80).** Your
current annual living expense (monthly × 12 + extra annual expenses) is
inflated to your retirement date, then inflated further every year of
retirement (default 8%/yr). Passive income (rent, dividends, etc.) and the
FD interest your corpus itself earns are projected forward too, and together
form your post-retirement income, netting off against that year's expenses.

**Medical expense.** Rather than a one-time lump sum reserve, this is treated
as a recurring annual expense: it grows from your current age (default 8%/yr)
and keeps growing every year through retirement, added directly into the
same year-by-year corpus calculation as your living expenses — not tacked on
separately afterwards.

**Required corpus.** The lump sum that, sitting in an FD at a fixed rate
(default 6%/yr), exactly funds this combined stream of inflating expenses
(living + medical), net of passive income and FD interest, down to ₹0 by
your life expectancy.

**Headline number.** "Additional sum required for investment" = Total
required corpus at retirement − projected future value of your current
investments. If your projected investments already exceed the requirement,
the app shows the projected surplus instead.

**Planning scenarios.** Three preset buttons (Aggressive / Moderate / I am
Positive) pre-fill all the growth and inflation rates at once — Aggressive
assumes higher inflation and lower growth (a cautious, plan-for-the-worst
scenario), I am Positive assumes lower inflation and higher growth (an
optimistic scenario). All rates stay editable afterwards.

All currency values are shown in Lacs/Crores (e.g. ₹1.25 Cr, ₹45.00 L) once
they cross ₹1,00,000. Your last submitted inputs are temporarily remembered
(server-side session) so going back to "Edit inputs" doesn't reset the form.

## Files

- `app.py` — Flask routes + all the calculation logic (`calculate_retirement`)
- `templates/index.html` — input form, scenario presets
- `templates/result.html` — results dashboard, breakdown tables, and
  Chart.js charts (investment growth + retirement corpus balance)
- `requirements.txt` — Flask + gunicorn
- `Procfile` / `render.yaml` — Render deployment config
