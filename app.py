"""
Retirement Calculator (Flask)

Models:
  - Accumulation phase (current age -> retirement age): each existing investment
    bucket (Mutual Funds, Shares, Commodities, LIC/NPS/EPF, Other) compounds
    every year at its own expected growth rate up to retirement age. Mutual
    Funds and Other Investments can also have a recurring monthly
    contribution (a Monthly SIP, and Other Monthly Savings respectively),
    starting now (the current age) and compounding every month through to
    retirement, at its own independently editable growth rate (defaults to
    match the bucket's lump-sum rate, but can be changed separately). A
    Monthly EMI (loan repayment) is netted out of that combined SIP + Other
    Monthly Savings pool *before* growth is applied, split proportionally
    across the two so each keeps compounding at its own rate on a smaller
    principal. Real Estate is tracked separately as an immovable asset
    (growth defaults to match Commodities) and is reported on its own -
    deliberately excluded from the investment total that offsets the
    required corpus, since it isn't something you'd typically liquidate to
    fund retirement income.
  - Decumulation phase (retirement age -> life expectancy): the required corpus
    is assumed to sit in a Fixed Deposit earning a fixed rate. Every year you
    withdraw that year's living expenses (which keep inflating every year, in
    retirement too) net of that year's passive income (rent/dividends, which
    also keeps growing every year) and pension/annuity income. Pension income
    exists only from retirement onward - it isn't projected forward before
    retirement, and only starts growing from the retirement age itself, at
    its own independently editable rate (defaults to match passive income's).
    The required corpus is the amount needed today (at retirement) so that
    this stream of withdrawals exactly drains the FD to zero by the target
    life expectancy.
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


def fv_monthly(monthly_amount, annual_rate, years):
    """Future value of a monthly contribution (e.g. an SIP), invested at the
    start of each month, over the given number of years.

    The stated rate is an *annual effective* rate (same convention used
    everywhere else in this app), so it's converted to the equivalent
    monthly rate rather than just divided by 12 - that keeps a 10% "growth"
    input compounding to exactly 10% a year, matching the lump-sum fv()
    calculations elsewhere.
    """
    months = int(round(years * 12))
    if monthly_amount <= 0 or months <= 0:
        return 0.0
    monthly_rate = (1 + annual_rate) ** (1 / 12) - 1
    if monthly_rate == 0:
        return monthly_amount * months
    return monthly_amount * (((1 + monthly_rate) ** months - 1) / monthly_rate) * (1 + monthly_rate)


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
    monthly_income = to_float(data, "monthly_income", 0)

    mf_value = to_float(data, "mf_value", 0)
    mf_growth = to_float(data, "mf_growth", 10.0) / 100
    sip_monthly = to_float(data, "sip_monthly", 0)
    sip_growth = to_float(data, "sip_growth", 10.0) / 100

    share_value = to_float(data, "share_value", 0)
    share_growth = to_float(data, "share_growth", 12.0) / 100

    commodity_value = to_float(data, "commodity_value", 0)
    commodity_growth = to_float(data, "commodity_growth", 8.0) / 100

    retirefund_value = to_float(data, "retirefund_value", 0)  # LIC/NPS/EPF
    retirefund_growth = to_float(data, "retirefund_growth", 8.0) / 100

    other_value = to_float(data, "other_value", 0)
    other_growth = to_float(data, "other_growth", 8.0) / 100
    other_monthly = to_float(data, "other_monthly", 0)
    other_monthly_growth = to_float(data, "other_monthly_growth", 8.0) / 100

    real_estate_value = to_float(data, "real_estate_value", 0)
    real_estate_growth = to_float(data, "real_estate_growth", 8.0) / 100  # defaults to match Commodities

    # Monthly EMI (loan repayments) comes out of the combined SIP + Other
    # Monthly Savings pool *before* growth is applied - i.e. it reduces the
    # principal being invested each month, not the final future value. Split
    # proportionally across the two so each keeps compounding at its own rate.
    monthly_emi = to_float(data, "monthly_emi", 0)
    gross_total_monthly = sip_monthly + other_monthly
    net_total_monthly = max(0.0, gross_total_monthly - monthly_emi)
    monthly_scale = (net_total_monthly / gross_total_monthly) if gross_total_monthly > 0 else 0.0
    sip_monthly_net = sip_monthly * monthly_scale
    other_monthly_net = other_monthly * monthly_scale

    passive_income = to_float(data, "passive_income", 0)
    passive_growth = to_float(data, "passive_growth", 5.0) / 100
    # Pension/annuity-style income that starts only at retirement (nothing to
    # project forward before then). Its growth rate defaults to match passive
    # income's but is independently editable.
    pension_annual = to_float(data, "pension_annual", 0)
    pension_growth = to_float(data, "pension_growth", 5.0) / 100

    inflation = to_float(data, "inflation", 8.0) / 100
    fd_rate = to_float(data, "fd_rate", 6.0) / 100

    medical_reserve_today = to_float(data, "medical_reserve", 10 * LAKH)
    medical_growth = to_float(data, "medical_growth", 8.0) / 100

    years_to_retirement = retire_age - current_age
    years_in_retirement = life_expectancy - retire_age

    # ---- Accumulation phase: grow each existing investment bucket to retirement ----
    # Mutual Funds and Other Investments also pick up the future value of
    # their recurring monthly contribution (SIP / other monthly savings, net
    # of any Monthly EMI - see above), each compounding from now (the current
    # age) to retirement, at its own independently editable growth rate
    # (defaults to match the bucket's lump-sum rate, but can be changed
    # separately). Real Estate is its own explicit bucket, growing at the
    # same rate as Commodities by default.
    fv_mf = fv(mf_value, mf_growth, years_to_retirement) + fv_monthly(sip_monthly_net, sip_growth, years_to_retirement)
    fv_share = fv(share_value, share_growth, years_to_retirement)
    fv_commodity = fv(commodity_value, commodity_growth, years_to_retirement)
    fv_retirefund = fv(retirefund_value, retirefund_growth, years_to_retirement)
    fv_other = fv(other_value, other_growth, years_to_retirement) + fv_monthly(other_monthly_net, other_monthly_growth, years_to_retirement)

    total_fv_investments = fv_mf + fv_share + fv_commodity + fv_retirefund + fv_other

    investment_breakdown = [
        {"label": "Mutual Funds", "current": mf_value, "growth_pct": mf_growth * 100, "monthly": sip_monthly_net, "monthly_growth_pct": sip_growth * 100, "future": fv_mf},
        {"label": "Shares", "current": share_value, "growth_pct": share_growth * 100, "monthly": 0, "monthly_growth_pct": 0, "future": fv_share},
        {"label": "Commodities", "current": commodity_value, "growth_pct": commodity_growth * 100, "monthly": 0, "monthly_growth_pct": 0, "future": fv_commodity},
        {"label": "LIC / NPS / EPF", "current": retirefund_value, "growth_pct": retirefund_growth * 100, "monthly": 0, "monthly_growth_pct": 0, "future": fv_retirefund},
        {"label": "Other Investments", "current": other_value, "growth_pct": other_growth * 100, "monthly": other_monthly_net, "monthly_growth_pct": other_monthly_growth * 100, "future": fv_other},
    ]

    # Real Estate is deliberately kept OUT of total_fv_investments / the
    # investment_breakdown above - it's an immovable asset, not something
    # you'd liquidate to fund retirement income, so it's computed separately
    # and shown only as an informational figure, never offsetting the
    # required corpus or affecting the shortfall/surplus calculation.
    fv_real_estate = fv(real_estate_value, real_estate_growth, years_to_retirement)

    # ---- Accumulation phase, year by year from current age itself ----
    # Shows exactly how each bucket compounds starting at the current age,
    # one year at a time, up to the retirement age (rather than jumping
    # straight from today's value to a single retirement-age total).
    accumulation_breakdown = []
    for yr in range(0, years_to_retirement + 1):
        yr_mf = fv(mf_value, mf_growth, yr) + fv_monthly(sip_monthly_net, sip_growth, yr)
        yr_share = fv(share_value, share_growth, yr)
        yr_commodity = fv(commodity_value, commodity_growth, yr)
        yr_retirefund = fv(retirefund_value, retirefund_growth, yr)
        yr_other = fv(other_value, other_growth, yr) + fv_monthly(other_monthly_net, other_monthly_growth, yr)
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
        # Pension/annuity income exists only from retirement onward, so there's
        # no pre-retirement leg to project - it simply grows year to year
        # within retirement (at its own rate), starting from the stated
        # amount in year 1.
        pension_t = fv(pension_annual, pension_growth, t - 1)
        total_passive_income_t = passive_t + pension_t
        net_withdrawal = total_expense_t - total_passive_income_t
        if net_withdrawal < 0:
            net_withdrawal = 0.0  # surplus income isn't withdrawn/added back in this model
        discounted = net_withdrawal / ((1 + fd_rate) ** (t - 1))
        required_living_corpus += discounted

        yearly_breakdown.append({
            "year": t,
            "age": retire_age + t - 1,
            "expense": expense_t,
            "medical_expense": medical_t,
            "total_expense": total_expense_t,
            "passive_income": passive_t,
            "pension_income": pension_t,
            "total_passive_income": total_passive_income_t,
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
        row["total_post_retirement_income"] = fd_interest + row["total_passive_income"]
        balance += fd_interest
        row["balance_end_of_year"] = balance

    # Medical expense is now folded into the yearly withdrawal stream above,
    # so the required corpus already covers it - no separate lump sum to add.
    total_required_corpus = required_living_corpus

    shortfall = total_required_corpus - total_fv_investments
    surplus = -shortfall if shortfall < 0 else 0.0

    # ---- Can leftover monthly income close the gap? ----
    # What's left of your monthly income once your EMI and your *current*
    # committed savings (SIP + Other Monthly Savings, before EMI netting -
    # this is the amount you've told us you're already setting aside) are
    # both accounted for. If that remainder were instead invested too, this
    # checks whether even a generous, best-case 15%/yr return on it would be
    # enough to close any shortfall above - a sanity check on whether "just
    # save more" is actually a viable fix, or whether other levers (more
    # passive income, lower post-retirement expenses) are needed instead.
    remaining_monthly_income = monthly_income - monthly_emi - gross_total_monthly
    BEST_CASE_GROWTH = 0.15
    extra_investable_monthly = max(0.0, remaining_monthly_income)
    hypothetical_extra_fv = fv_monthly(extra_investable_monthly, BEST_CASE_GROWTH, years_to_retirement)
    projected_total_with_extra = total_fv_investments + hypothetical_extra_fv
    shortfall_after_extra = total_required_corpus - projected_total_with_extra
    extra_savings_not_enough = shortfall > 0 and shortfall_after_extra > 0

    return {
        "errors": [],
        "current_age": current_age,
        "retire_age": retire_age,
        "life_expectancy": life_expectancy,
        "years_to_retirement": years_to_retirement,
        "years_in_retirement": years_in_retirement,

        "monthly_expenses": monthly_expenses,
        "extra_annual_expenses": extra_annual_expenses,
        "monthly_income": monthly_income,
        "current_annual_expense": current_annual_expense,
        "expense_at_retirement": expense_at_retirement,

        "passive_income": passive_income,
        "passive_growth_pct": passive_growth * 100,
        "passive_at_retirement": passive_at_retirement,
        "pension_annual": pension_annual,
        "pension_growth_pct": pension_growth * 100,

        "inflation_pct": inflation * 100,
        "fd_rate_pct": fd_rate * 100,

        "medical_reserve_today": medical_reserve_today,
        "medical_growth_pct": medical_growth * 100,
        "medical_at_retirement": medical_at_retirement,

        "investment_breakdown": investment_breakdown,
        "total_fv_investments": total_fv_investments,
        "accumulation_breakdown": accumulation_breakdown,
        "real_estate_value": real_estate_value,
        "real_estate_growth_pct": real_estate_growth * 100,
        "fv_real_estate": fv_real_estate,

        "monthly_emi": monthly_emi,
        "gross_total_monthly": gross_total_monthly,
        "net_total_monthly": net_total_monthly,

        "required_living_corpus": required_living_corpus,
        "total_required_corpus": total_required_corpus,

        "shortfall": shortfall if shortfall > 0 else 0.0,
        "surplus": surplus,

        "remaining_monthly_income": remaining_monthly_income,
        "extra_investable_monthly": extra_investable_monthly,
        "best_case_growth_pct": BEST_CASE_GROWTH * 100,
        "hypothetical_extra_fv": hypothetical_extra_fv,
        "shortfall_after_extra": shortfall_after_extra if shortfall_after_extra > 0 else 0.0,
        "extra_savings_not_enough": extra_savings_not_enough,

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
