"""
Retirement Calculator (Flask)

Models:
  - Accumulation phase (current age -> retirement age): each existing investment
    bucket (Mutual Funds, Shares, Commodities, LIC/NPS/EPF, Other) compounds
    every year at its own expected growth rate up to retirement age.
  - Decumulation phase (retirement age -> life expectancy): the required corpus
    is assumed to sit in a Fixed Deposit earning a fixed rate. Every year you
    withdraw that year's living expenses (which keep inflating every year, in
    retirement too) net of that year's passive income (rent/dividends, which
    also keeps growing every year). The required corpus is the amount needed
    today (at retirement) so that this stream of withdrawals exactly drains
    the FD to zero by the target life expectancy.
  - The medical emergency reserve (default INR 10,00,000 in today's money) is
    treated as a recurring annual expense, not a separate lump sum: it grows
    at its own rate from the current age, and continues growing every year
    through retirement too, adding to that year's living expense inside the
    same corpus-sizing calculation (so it is fully reflected in the required
    corpus, not bolted on afterwards).
  - The "additional sum required for investment" is the gap between the total
    required corpus at retirement and the projected future value of the
    investments the user already holds.

All rates are editable in the form; the defaults reflect the assumptions
given in the brief (8% inflation, 10% mutual fund growth, 5% passive-income
growth, 6% FD return, life expectancy 80, 8% medical-cost inflation).
"""

import os

from flask import Flask, render_template, request, session

app = Flask(__name__)
# Used only to sign the session cookie that temporarily remembers what the
# user last typed into the form (so "Edit inputs" doesn't come back blank -
# and so it survives a free-tier dyno/instance restart on Render). No
# sensitive data is stored in it, but you can override this with your own
# SECRET_KEY environment variable in Render's dashboard if you'd rather not
# use the built-in fallback.
app.secret_key = os.environ.get(
    "SECRET_KEY",
    "bcb81388ba3fa4b3c84a72b491ac7714734e0acf2c8cb49c60797a22a6ca9f1b",
)

LAKH = 100000
CRORE = 100 * LAKH


def inr_fmt(value):
    """Format a rupee amount using the Indian Lac/Crore convention.

    >= 1 Crore (1,00,00,000)  -> "₹X.XX Cr"
    >= 1 Lac    (1,00,000)    -> "₹X.XX L"
    otherwise                  -> "₹X,XXX" (plain, comma-grouped)
    """
    try:
        value = float(value)
    except (TypeError, ValueError):
        return value

    sign = "-" if value < 0 else ""
    value = abs(value)

    if value >= CRORE:
        return f"{sign}₹{value / CRORE:,.2f} Cr"
    if value >= LAKH:
        return f"{sign}₹{value / LAKH:,.2f} L"
    return f"{sign}₹{value:,.0f}"


app.jinja_env.filters["inr"] = inr_fmt


def to_float(form, key, default=0.0):
    raw = (form.get(key) or "").strip()
    if raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def to_int(form, key, default=0):
    raw = (form.get(key) or "").strip()
    if raw == "":
        return default
    try:
        return int(float(raw))
    except ValueError:
        return default


def fv(principal, rate, years):
    """Future value of a lump sum compounding annually."""
    return principal * ((1 + rate) ** years)


def calculate_retirement(data):
    errors = []

    current_age = to_int(data, "current_age", 30)
    retire_age = to_int(data, "retire_age", 60)
    life_expectancy = to_int(data, "life_expectancy", 80)

    if retire_age <= current_age:
        errors.append("Desired retirement age must be greater than current age.")
    if life_expectancy <= retire_age:
        errors.append("Life expectancy must be greater than retirement age.")

    if errors:
        return {"errors": errors}

    monthly_expenses = to_float(data, "monthly_expenses", 0)
    extra_annual_expenses = to_float(data, "extra_annual_expenses", 0)

    mf_value = to_float(data, "mf_value", 0)
    mf_growth = to_float(data, "mf_growth", 10.0) / 100

    share_value = to_float(data, "share_value", 0)
    share_growth = to_float(data, "share_growth", 12.0) / 100

    commodity_value = to_float(data, "commodity_value", 0)
    commodity_growth = to_float(data, "commodity_growth", 8.0) / 100

    retirefund_value = to_float(data, "retirefund_value", 0)  # LIC/NPS/EPF
    retirefund_growth = to_float(data, "retirefund_growth", 8.0) / 100

    other_value = to_float(data, "other_value", 0)
    other_growth = to_float(data, "other_growth", 8.0) / 100

    passive_income = to_float(data, "passive_income", 0)
    passive_growth = to_float(data, "passive_growth", 5.0) / 100

    inflation = to_float(data, "inflation", 8.0) / 100
    fd_rate = to_float(data, "fd_rate", 6.0) / 100

    medical_reserve_today = to_float(data, "medical_reserve", 10 * LAKH)
    medical_growth = to_float(data, "medical_growth", 8.0) / 100

    years_to_retirement = retire_age - current_age
    years_in_retirement = life_expectancy - retire_age

    # ---- Accumulation phase: grow each existing investment bucket to retirement ----
    fv_mf = fv(mf_value, mf_growth, years_to_retirement)
    fv_share = fv(share_value, share_growth, years_to_retirement)
    fv_commodity = fv(commodity_value, commodity_growth, years_to_retirement)
    fv_retirefund = fv(retirefund_value, retirefund_growth, years_to_retirement)
    fv_other = fv(other_value, other_growth, years_to_retirement)

    total_fv_investments = fv_mf + fv_share + fv_commodity + fv_retirefund + fv_other

    investment_breakdown = [
        {"label": "Mutual Funds", "current": mf_value, "growth_pct": mf_growth * 100, "future": fv_mf},
        {"label": "Shares", "current": share_value, "growth_pct": share_growth * 100, "future": fv_share},
        {"label": "Commodities", "current": commodity_value, "growth_pct": commodity_growth * 100, "future": fv_commodity},
        {"label": "LIC / NPS / EPF", "current": retirefund_value, "growth_pct": retirefund_growth * 100, "future": fv_retirefund},
        {"label": "Other Investments", "current": other_value, "growth_pct": other_growth * 100, "future": fv_other},
    ]

    # ---- Accumulation phase, year by year from current age itself ----
    # Shows exactly how each bucket compounds starting at the current age,
    # one year at a time, up to the retirement age (rather than jumping
    # straight from today's value to a single retirement-age total).
    accumulation_breakdown = []
    for yr in range(0, years_to_retirement + 1):
        yr_mf = fv(mf_value, mf_growth, yr)
        yr_share = fv(share_value, share_growth, yr)
        yr_commodity = fv(commodity_value, commodity_growth, yr)
        yr_retirefund = fv(retirefund_value, retirefund_growth, yr)
        yr_other = fv(other_value, other_growth, yr)
        accumulation_breakdown.append({
            "year": yr,
            "age": current_age + yr,
            "mf": yr_mf,
            "share": yr_share,
            "commodity": yr_commodity,
            "retirefund": yr_retirefund,
            "other": yr_other,
            "total": yr_mf + yr_share + yr_commodity + yr_retirefund + yr_other,
        })

    # ---- Expenses and passive income projected to the first day of retirement ----
    current_annual_expense = monthly_expenses * 12 + extra_annual_expenses
    expense_at_retirement = fv(current_annual_expense, inflation, years_to_retirement)
    passive_at_retirement = fv(passive_income, passive_growth, years_to_retirement)
    # Medical expense also grows from the current age through to retirement
    # age, then keeps growing every year in retirement (see loop below) -
    # it's an ongoing expense, not a one-time lump sum reserve.
    medical_at_retirement = fv(medical_reserve_today, medical_growth, years_to_retirement)

    # ---- Decumulation phase: year-by-year corpus needed so the FD drains to 0 ----
    required_living_corpus = 0.0
    yearly_breakdown = []

    for t in range(1, years_in_retirement + 1):
        expense_t = fv(expense_at_retirement, inflation, t - 1)
        medical_t = fv(medical_at_retirement, medical_growth, t - 1)
        total_expense_t = expense_t + medical_t
        passive_t = fv(passive_at_retirement, passive_growth, t - 1)
        net_withdrawal = total_expense_t - passive_t
        if net_withdrawal < 0:
            net_withdrawal = 0.0  # surplus passive income isn't withdrawn/added back in this model
        discounted = net_withdrawal / ((1 + fd_rate) ** (t - 1))
        required_living_corpus += discounted

        yearly_breakdown.append({
            "year": t,
            "age": retire_age + t - 1,
            "expense": expense_t,
            "medical_expense": medical_t,
            "total_expense": total_expense_t,
            "passive_income": passive_t,
            "net_withdrawal": net_withdrawal,
        })

    # Simulate the FD balance year by year (withdraw at start of year, then the
    # remaining balance earns FD interest for the rest of the year). The FD
    # interest and the passive income together make up that year's total
    # post-retirement income, shown alongside the expense it has to cover.
    balance = required_living_corpus
    for row in yearly_breakdown:
        balance -= row["net_withdrawal"]
        row["balance_after_withdrawal"] = balance
        fd_interest = balance * fd_rate
        row["fd_interest_earned"] = fd_interest
        row["total_post_retirement_income"] = fd_interest + row["passive_income"]
        balance += fd_interest
        row["balance_end_of_year"] = balance

    # Medical expense is now folded into the yearly withdrawal stream above,
    # so the required corpus already covers it - no separate lump sum to add.
    total_required_corpus = required_living_corpus

    shortfall = total_required_corpus - total_fv_investments
    surplus = -shortfall if shortfall < 0 else 0.0

    return {
        "errors": [],
        "current_age": current_age,
        "retire_age": retire_age,
        "life_expectancy": life_expectancy,
        "years_to_retirement": years_to_retirement,
        "years_in_retirement": years_in_retirement,

        "monthly_expenses": monthly_expenses,
        "extra_annual_expenses": extra_annual_expenses,
        "current_annual_expense": current_annual_expense,
        "expense_at_retirement": expense_at_retirement,

        "passive_income": passive_income,
        "passive_growth_pct": passive_growth * 100,
        "passive_at_retirement": passive_at_retirement,

        "inflation_pct": inflation * 100,
        "fd_rate_pct": fd_rate * 100,

        "medical_reserve_today": medical_reserve_today,
        "medical_growth_pct": medical_growth * 100,
        "medical_at_retirement": medical_at_retirement,

        "investment_breakdown": investment_breakdown,
        "total_fv_investments": total_fv_investments,
        "accumulation_breakdown": accumulation_breakdown,

        "required_living_corpus": required_living_corpus,
        "total_required_corpus": total_required_corpus,

        "shortfall": shortfall if shortfall > 0 else 0.0,
        "surplus": surplus,

        "yearly_breakdown": yearly_breakdown,
    }


@app.route("/", methods=["GET"])
def index():
    # Repopulate from whatever was last submitted this session, so navigating
    # back via "Edit inputs" doesn't dump the user back to blank defaults.
    return render_template("index.html", form=session.get("last_input"))


@app.route("/calculate", methods=["POST"])
def calculate():
    # Temporarily remember these inputs (server-side session, cleared when
    # the browser session ends) so the form can be repopulated later.
    session["last_input"] = request.form.to_dict()

    result = calculate_retirement(request.form)
    if result.get("errors"):
        return render_template("index.html", errors=result["errors"], form=request.form)
    return render_template("result.html", r=result)


if __name__ == "__main__":
    app.run(debug=True)
