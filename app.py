"""Nordic Customer Success Radar: Streamlit dashboard.

Run:  streamlit run app.py
"""

from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from csm import catalog, generate, journal, links, pipeline
from csm.config import AS_OF, HEALTH_BANDS, HEALTH_WEIGHTS, WEAKEST_PART_MARGIN
from csm.db import DB_PATH, connect
from csm.metrics import METRIC_DOCS
from csm.signals import load_rules
from csm.views import (CHECK, FIX, READY, SOFTWARE, coverage, effectiveness, journal_state, load, main_contact,
                       needs_decision, region_summary, sales_note)

st.set_page_config(page_title="Nordic CS Radar", page_icon=":material/radar:", layout="wide")

# --- Palette (validated reference palette, light mode) -------------------------
COUNTRY_COLORS = {"NO": "#2a78d6", "DK": "#eb6834", "SE": "#1baf7a", "FI": "#eda100"}
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}
BAND_COLORS = {label: STATUS[role] for _, label, role in HEALTH_BANDS}
BAND_BADGE = {"Healthy": ("green", "check_circle"), "Watch": ("orange", "visibility"),
              "At risk": ("orange", "warning"), "Critical": ("red", "error")}
SEVERITY_BADGE = {"low": ("gray", "info"), "medium": ("orange", "warning"),
                  "high": ("red", "priority_high"), "critical": ("red", "error")}
READINESS_COLORS = {READY: STATUS["good"], CHECK: STATUS["warning"], FIX: STATUS["serious"]}
READINESS_BADGE = {READY: ("green", "check_circle"), CHECK: ("orange", "visibility"), FIX: ("red", "build")}
INK, INK_2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
COUNTRY_NAMES = {"NO": "Norway", "DK": "Denmark", "SE": "Sweden", "FI": "Finland"}
AREA_BADGE = {"Security": ("blue", "shield"), "Capacity": ("violet", "bolt"), "Reliability": ("orange", "build"),
              "General": ("gray", "person"), "—": ("gray", "remove")}
MODULE_SHORT = {"ASSET": "Asset Mgmt", "NFM": "Fault Mgmt", "OTC": "OT Companion", "SIEM": "SIEM", "MDR": "MDR",
                "DGM": "Grid Mgmt", "LM": "Load Mgmt", "PRM": "Power Res.", "SEM": "Energy Mgmt"}
COVERAGE_STYLE = {"Used well": "#dff3df", "Not delivering": "#fbe1d6", "Opportunity": "#dbe8fa",
                  "Not used": "#f0efec", "Not relevant": "#fcfcfb"}


def badge(label, color, icon):
    return f":{color}-badge[:material/{icon}: {label}]"


def area_badge(area):
    return badge(area, *AREA_BADGE.get(area, AREA_BADGE["General"]))


def band_badge(band):
    return badge(band, *BAND_BADGE[band])


def eur(x):
    if x >= 1_000_000:
        return f"€{x / 1_000_000:.1f}M"
    if x >= 1_000:
        return f"€{x / 1_000:.0f}k"
    return f"€{x:.0f}"


def style(fig, height=320, legend=True):
    fig.update_layout(
        height=height, margin=dict(l=8, r=8, t=8, b=8),
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif", color=INK_2, size=13),
        showlegend=legend, legend=dict(orientation="h", y=1.08, x=0, title=None),
        hoverlabel=dict(bgcolor="white", font_color=INK), barcornerradius=4,
    )
    fig.update_xaxes(gridcolor=GRID, linecolor=AXIS, tickfont_color=MUTED, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, linecolor=AXIS, tickfont_color=MUTED, zeroline=False)
    return fig


def open_account(account_id):
    st.session_state["account_id"] = int(account_id)
    st.switch_page(PAGES["account"])


def open_button(container, label, key, account_id):
    if container.button(label, key=key, width="stretch"):
        open_account(account_id)


# --- Data ------------------------------------------------------------------------
@st.cache_data
def get_data(db_mtime):
    conn = connect()
    data = load(conn)
    conn.close()
    return data


def db_is_current():
    """False if the database is missing or was built by an older version of the schema."""
    if not DB_PATH.exists():
        return False
    conn = connect()
    try:
        conn.execute("SELECT suggested_action FROM signals LIMIT 1")
        conn.execute("SELECT email FROM contacts LIMIT 1")
        conn.execute("SELECT area FROM signals LIMIT 1")
        conn.execute("SELECT 1 FROM module_kpi_weekly LIMIT 1")
        return True
    except Exception:
        return False
    finally:
        conn.close()


if not db_is_current():
    with st.spinner("Generating synthetic portfolio…"):
        generate.build().close()
        pipeline.analyse(connect())
DATA = get_data(DB_PATH.stat().st_mtime)

# The CSM's own input lives in a separate journal database and is read fresh on every run.
JCONN = journal.connect()
STATE = journal_state(JCONN, DATA)
TODAY = journal.today()
RULES = {r["id"]: r for r in load_rules()}
SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
STATUS_BADGE = {"Needs decision": ("red", "pending_actions"), "In progress": ("blue", "autorenew"),
                "Monitoring": ("gray", "schedule"), "Dismissed": ("gray", "block"), "Action done": ("green", "task_alt")}
MEETING_MINUTES = {"Call": 30, "On-site visit": 120, "Success review / QBR": 60, "Training / workshop": 90}
CUSTOMER_MESSAGES = {
    "Call": ("Short call this week?",
             "Hi {first},\n\nI'd like to hear how things are going with Electrification X on your side. "
             "Do you have 20 minutes this week?\n\nBest regards"),
    "On-site visit": ("Visit to {account}",
                      "Hi {first},\n\nI'd like to visit you and see how you use Electrification X in daily operations. "
                      "Would a day in the next two weeks work?\n\nBest regards"),
    "Success review / QBR": ("Success review: results and next steps",
                             "Hi {first},\n\nIt's time to look back at what we agreed and set objectives for the next "
                             "quarter. Could we find an hour in the coming weeks?\n\nBest regards"),
    "Email / check-in": ("Checking in", "Hi {first},\n\nJust checking in: is there anything we can help with right "
                                        "now?\n\nBest regards"),
    "Training / workshop": ("Training for your team",
                            "Hi {first},\n\nWe could run a short session for more of your team, for example field "
                            "technicians or the OT security team. Would that be useful?\n\nBest regards"),
}
# Internal hand-offs go to placeholder addresses (.example never delivers).
INTERNAL_RECIPIENTS = {"Escalate internally": "support-escalation@siemens-team.example",
                       "Involve Sales": "sales-nordics@siemens-team.example"}


def clean(record):
    """Row dict with pandas NaN turned into None."""
    return {k: (None if isinstance(v, float) and pd.isna(v) else v) for k, v in record.items()}


def status_badge(status):
    return badge(status, *STATUS_BADGE[status])


def account_name(account_id):
    return DATA["summary"].set_index("id").loc[account_id, "name"]


def account_signals(account_id, kind=None):
    sig = STATE["signals"]
    sig = sig[sig["account_id"] == account_id]
    if kind:
        sig = sig[sig["kind"] == kind]
    return sig.assign(o=sig["severity"].map(SEV_ORDER)).sort_values("o")


def refresh(reanalyse=False):
    """Save done: re-run the current-week analysis if contact data changed, then redraw."""
    if reanalyse:
        conn = connect()
        pipeline.analyse(conn, journal_conn=JCONN, history=False)
        conn.close()
        get_data.clear()
    st.rerun()


def decide_button(container, account_id, rule_ids, key, label="Decide"):
    rule_ids = list(rule_ids)
    if rule_ids and container.button(label, key=key, type="primary", width="stretch", icon=":material/gavel:"):
        decide_dialog(account_id, rule_ids)


@st.dialog("Decide what to do", width="large")
def decide_dialog(account_id, rule_ids):
    sig = account_signals(account_id)
    sig = sig[sig["rule_id"].isin(rule_ids)]
    st.markdown(f"**{account_name(account_id)}**")
    labels = {r.rule_id: f"{r.title} ({r.severity})" for r in sig.itertuples()}
    chosen = st.multiselect("Signals this decision covers", list(labels), default=list(labels), format_func=labels.get)
    picked = sig[sig["rule_id"].isin(chosen)] if chosen else sig
    for r in picked.itertuples():
        st.caption(f"{r.title}: {r.reason}")
    top = picked.iloc[0]
    suggested = top["suggested_action"] or "Call"
    options = list(journal.DECISIONS)
    decision = st.selectbox("Decision", options, index=options.index(suggested),
                            help=f"Suggested for this signal: {suggested}")
    due_on = review_on = None
    if decision == "Monitor":
        review_on = st.date_input("Look at it again on", TODAY + timedelta(days=14), min_value=TODAY)
        note = st.text_area("Why wait?")
    elif decision == "Dismiss":
        note = st.text_area("Why is this not a real problem? (required)")
        st.caption(f"The signal stays quiet for {journal.DISMISS_DAYS} days. Dismissal reasons help tune the rules.")
    else:
        due_on = st.date_input("Due", TODAY + timedelta(days=journal.DUE_DAYS[top["severity"]]), min_value=TODAY)
        note = st.text_area("Note (optional)")
    if st.button("Save decision", type="primary", disabled=not chosen):
        if decision == "Dismiss" and not note.strip():
            st.error("Please give a reason for dismissing.")
            return
        journal.decide(JCONN, account_id, chosen, decision, note, due_on, review_on)
        refresh()


@st.dialog("Log the result")
def complete_dialog(d):
    st.markdown(f"**{d['decision']}** · {d['account']}")
    outcome = st.radio("Outcome", journal.OUTCOMES, horizontal=True)
    agreed = None
    if d["decision"] == "Success review / QBR":
        agreed = st.checkbox("Objectives agreed with the customer", value=True)
    note = st.text_area("What happened?")
    direct, _ = journal.DECISIONS[d["decision"]]
    if direct:
        st.caption("This counts as direct contact with the customer and updates the account's signals.")
    left, right = st.columns(2)
    if left.button("Save result", type="primary", width="stretch"):
        journal.complete(JCONN, d["id"], outcome, note, agreed)
        refresh(reanalyse=direct)
    if right.button("Cancel the action instead", width="stretch"):
        journal.cancel(JCONN, d["id"])
        refresh()


def decision_reasons(d):
    sig = STATE["signals"]
    reasons = []
    for rid in d["rule_ids"].split(","):
        hit = sig[(sig["account_id"] == d["account_id"]) & (sig["rule_id"] == rid)]
        reasons.append(f"{hit.iloc[0]['title']}: {hit.iloc[0]['reason']}" if not hit.empty
                       else RULES[rid]["title"] if rid in RULES else rid)
    return reasons


@st.dialog("Salesforce task (preview)", width="large")
def salesforce_dialog(d):
    st.caption("With an integration, the radar would create this task through the Salesforce API, so Sales and "
               "account management see it too. Calls and visits logged in Salesforce would flow back into the "
               "radar as direct contact.")
    st.json(links.salesforce_task(d, d["account"], decision_reasons(d), d["crm_task_id"]))


def handoff_links(d, key):
    """Outlook, Teams, calendar and Salesforce hand-offs for one action."""
    contact = main_contact(DATA, d["account_id"])
    acc = DATA["summary"].set_index("id").loc[d["account_id"]]
    kind = d["decision"]
    if kind in CUSTOMER_MESSAGES:
        to = [contact["email"]] if contact is not None else []
        first = contact["name"].split()[0] if contact is not None else ""
        subject, body = CUSTOMER_MESSAGES[kind]
        subject, body = subject.format(account=acc["name"]), body.format(first=first)
    else:
        if kind == "Go through partner" and isinstance(acc["partner"], str):
            to = [f"contact@{acc['partner'].split()[0].lower()}.example"]
        else:
            to = [INTERNAL_RECIPIENTS.get(kind, "account-team@siemens-team.example")]
        subject = f"{acc['name']}: {kind.lower()}"
        body = "Context from the CS radar:\n" + "\n".join(f"- {r}" for r in decision_reasons(d))
        if d.get("note"):
            body += f"\n\nNote: {d['note']}"
    start = links.meeting_start(date.fromisoformat(d["due_on"]))
    minutes = MEETING_MINUTES.get(kind, 30)
    cols = st.columns(4)
    cols[0].link_button("Outlook email", links.mailto(to, subject, body), icon=":material/mail:", width="stretch")
    if kind in MEETING_MINUTES:
        cols[1].link_button("Teams meeting", links.teams_meeting(f"{acc['name']}: {kind}", start, minutes, to, body),
                            icon=":material/videocam:", width="stretch")
    else:
        cols[1].link_button("Teams chat", links.teams_chat(to, f"{subject}\n{body}"), icon=":material/chat:",
                            width="stretch")
    cols[2].download_button("Calendar (.ics)", links.ics(f"decision-{d['id']}", f"{acc['name']}: {kind}", start, minutes,
                                                         body, to, "Microsoft Teams"),
                            file_name=f"{kind.split()[0].lower()}-{d['id']}.ics", mime="text/calendar",
                            icon=":material/event:", width="stretch", key=f"ics-{key}")
    if cols[3].button("Salesforce task", key=f"sf-{key}", icon=":material/cloud:", width="stretch"):
        salesforce_dialog(d)


def action_card(d, key):
    with st.container(border=True):
        head, btn = st.columns([5, 1])
        due = date.fromisoformat(d["due_on"])
        days = (due - TODAY).days
        due_badge = (badge(f"Overdue by {-days} days", "red", "alarm") if days < 0 else
                     badge("Due today", "orange", "today") if days == 0 else badge(f"Due in {days} days", "blue", "event"))
        head.markdown(f"**{d['decision']}** · {d['account']} &nbsp; {due_badge}  \n"
                      f":gray[Covers: {' · '.join(decision_reasons(d))}]"
                      + (f"  \n{d['note']}" if d.get("note") else ""))
        if btn.button("Log result", key=f"done-{key}", width="stretch", icon=":material/check:"):
            complete_dialog(d)
        handoff_links(d, key)


def filtered():
    countries = st.session_state.get("countries") or list(COUNTRY_NAMES)
    s = DATA["summary"][DATA["summary"]["country"].isin(countries)]
    o = DATA["opportunities"]
    o = o[o["country"].isin(countries)] if not o.empty else o
    return s, o


# --- Pages -------------------------------------------------------------------------
def page_portfolio():
    s, o = filtered()
    st.title("Portfolio overview")
    st.caption(f"As of {AS_OF:%d %B %Y} · {len(s)} fictional Nordic accounts · synthetic data")

    arr = s["arr_eur"].sum()
    renew = s[s["days_to_renewal"] <= 90]
    at_risk = s[s["at_risk"]]
    ready = o[o["readiness"] == READY] if not o.empty else o
    cols = st.columns(5)
    cols[0].metric("ARR", eur(arr), border=True)
    cols[1].metric("Health (ARR-weighted)", f"{(s['health'] * s['arr_eur']).sum() / arr:.0f} / 100", border=True)
    cols[2].metric("ARR at risk", eur(at_risk["arr_eur"].sum()), f"{len(at_risk)} accounts",
                   delta_color="off", delta_arrow="off", border=True,
                   help="Accounts with health below 60 or a critical risk signal")
    cols[3].metric("Renewals in 90 days", len(renew), eur(renew["arr_eur"].sum()), delta_color="off", delta_arrow="off", border=True)
    cols[4].metric("Expansion ready now", eur(ready["est_value_eur"].sum() if not ready.empty else 0),
                   f"{len(ready)} opportunities", delta_color="off", delta_arrow="off", border=True)

    nd = needs_decision(STATE)
    nd = nd[nd["account_id"].isin(s["id"])]
    dec = STATE["decisions"]
    overdue = dec[(dec["status"] == "open") & (dec["due_on"] < TODAY.isoformat())] if not dec.empty else dec
    st.page_link(PAGES["actions"], icon=":material/task_alt:",
                 label=f"{len(nd)} signals on {nd['account_id'].nunique()} accounts need your decision · "
                       f"{len(overdue)} actions overdue → Action center")

    left, right = st.columns(2)
    with left:
        st.subheader("ARR by health band")
        fig = go.Figure()
        countries = [c for c in COUNTRY_NAMES if c in set(s["country"])]
        for _, band, _ in HEALTH_BANDS:
            vals = [s[(s["country"] == c) & (s["band"] == band)]["arr_eur"].sum() for c in countries]
            fig.add_bar(name=band, x=[COUNTRY_NAMES[c] for c in countries], y=vals, marker_color=BAND_COLORS[band],
                        marker_line=dict(color=SURFACE, width=2),
                        hovertemplate="%{x} · " + band + ": €%{y:,.0f}<extra></extra>")
        fig.update_layout(barmode="stack")
        fig.update_yaxes(tickprefix="€", tickformat="~s")
        st.plotly_chart(style(fig), width="stretch")
    with right:
        st.subheader("Health trend by region")
        h = DATA["health"].merge(s[["id", "country", "arr_eur"]], left_on="account_id", right_on="id")
        h["w"] = h["total"] * h["arr_eur"]
        trend = h.groupby(["country", "as_of"]).agg(w=("w", "sum"), arr=("arr_eur", "sum")).reset_index()
        trend["health"] = trend["w"] / trend["arr"]
        fig = go.Figure()
        for c, g in trend.groupby("country"):
            fig.add_scatter(x=g["as_of"], y=g["health"], name=COUNTRY_NAMES[c], mode="lines",
                            line=dict(color=COUNTRY_COLORS[c], width=2),
                            hovertemplate=COUNTRY_NAMES[c] + " %{x}: %{y:.0f}<extra></extra>")
        fig.update_layout(hovermode="x unified")
        fig.update_yaxes(range=[40, 100], title="ARR-weighted health")
        st.plotly_chart(style(fig), width="stretch")

    left, right = st.columns(2)
    with left:
        st.subheader("Top risks this week")
        top = s[s["n_risks"] > 0].sort_values("priority", ascending=False).head(6)
        for r in top.itertuples():
            sig = DATA["signals"][(DATA["signals"]["account_id"] == r.id) & (DATA["signals"]["kind"] == "risk")]
            worst = sig.assign(p=sig["severity"].map({"low": 1, "medium": 3, "high": 6, "critical": 10})) \
                .sort_values("p", ascending=False).iloc[0]
            with st.container(border=True):
                a, b = st.columns([4, 1])
                a.markdown(f"**{r.name}** · {COUNTRY_NAMES[r.country]} · {eur(r.arr_eur)}  \n"
                           f"{band_badge(r.band)} &nbsp; {worst['title']}: {worst['reason']}")
                open_button(b, "Open", f"risk-{r.id}", r.id)
    with right:
        st.subheader("Top expansion opportunities")
        for r in (ready.head(6).itertuples() if not ready.empty else []):
            with st.container(border=True):
                a, b = st.columns([4, 1])
                a.markdown(f"**{r.account}** · {COUNTRY_NAMES[r.country]} · **{eur(r.est_value_eur)}**  \n"
                           f"{r.module}: {r.reasons[0]}")
                open_button(b, "Open", f"exp-{r.account_id}-{r.module_code}", r.account_id)


def page_regions():
    st.title("Regions")
    st.caption("Same signals everywhere, but each market needs a different emphasis.")
    regions = region_summary(DATA)
    cols = st.columns(4)
    for col, r in zip(cols, regions.itertuples()):
        with col.container(border=True):
            st.subheader(r.name)
            nis2_color = "green" if r.nis2_status == "In force" else "orange"
            st.markdown(badge(f"NIS2: {r.nis2_status}", nis2_color, "gavel"))
            st.caption(r.market_note)
            a, b = st.columns(2)
            a.metric("Accounts", r.accounts)
            b.metric("ARR", eur(r.arr_eur))
            a.metric("Health", f"{r.health_arr_weighted:.0f}")
            b.metric("ARR at risk", eur(r.arr_at_risk))
            a.metric("Top share", f"{r.top_account_share:.0%}", help="Largest account's share of the region's ARR")
            b.metric("Via partners", f"{r.partner_share:.0%}", help="Share of ARR in partner-led accounts")
            a.metric("Open risks", r.open_risks)
            b.metric("Expansion", eur(r.expansion_eur), help=f"Ready now: {eur(r.expansion_ready_eur)}")
            st.caption(r.nis2_note)
            grid_color = "red" if r.grid_pressure == "High" else "violet"
            st.markdown(badge(f"Grid pressure: {r.grid_pressure}", grid_color, "bolt"))
            st.caption(f"{r.grid_accounts} of our accounts are in constrained areas. {r.grid_note}")

    st.subheader("How concentrated is each region?")
    st.caption("Each block is one account's share of its region's ARR. Denmark rests on three accounts; "
               "Norway is spread over many. The risk radar weights problems by this share.")
    s = DATA["summary"]
    fig = go.Figure()
    for c in reversed(list(COUNTRY_NAMES)):
        g = s[s["country"] == c].sort_values("arr_eur", ascending=False)
        total = g["arr_eur"].sum()
        offset = 0
        for r in g.itertuples():
            share = r.arr_eur / total
            fig.add_bar(y=[COUNTRY_NAMES[c]], x=[share], base=offset, orientation="h", showlegend=False,
                        marker=dict(color=COUNTRY_COLORS[c], line=dict(color=SURFACE, width=2)),
                        text=f"{share:.0%}" if share >= 0.12 else "", textposition="inside",
                        insidetextfont=dict(color="#0b0b0b" if c == "FI" else "white"),
                        hovertemplate=f"{r.name}: {share:.0%} of {COUNTRY_NAMES[c]} ARR ({eur(r.arr_eur)})<extra></extra>")
            offset += share
    fig.update_layout(barmode="overlay", bargap=0.35)
    fig.update_xaxes(tickformat=".0%", range=[0, 1])
    st.plotly_chart(style(fig, height=260, legend=False), width="stretch")

    st.subheader("Partners")
    st.caption("In partner-led accounts Siemens sees usage data but not always the relationship. "
               "Days since direct contact shows where the view is getting old.")
    m = DATA["metrics"]
    p = s[s["channel"] == "Partner"].copy()
    p["days_since_direct"] = p["id"].map(lambda i: m[i]["days_since_direct_touch"])
    table = p.groupby(["partner", "country"]).agg(
        accounts=("id", "count"), arr=("arr_eur", "sum"), health=("health", "mean"),
        days_since_direct=("days_since_direct", "max"), open_risks=("n_risks", "sum")).reset_index()
    table["country"] = table["country"].map(COUNTRY_NAMES)
    st.dataframe(table, hide_index=True, width="stretch", column_config={
        "partner": "Partner", "country": "Country", "accounts": "Accounts",
        "arr": st.column_config.NumberColumn("ARR", format="euro"),
        "health": st.column_config.ProgressColumn("Avg health", min_value=0, max_value=100, format="%.0f"),
        "days_since_direct": st.column_config.NumberColumn("Longest without direct contact", format="%d days"),
        "open_risks": "Open risks",
    })


def page_risk():
    s, _ = filtered()
    st.title("Risk radar")
    st.caption("Accounts with risk signals, ranked by priority: severity points weighted by the account's share "
               "of its region's ARR. The same problem ranks higher where one customer carries the region.")
    risky = s[s["n_risks"] > 0].sort_values("priority", ascending=False)

    table = risky[["id", "name", "country", "focus", "health", "band", "arr_eur", "days_to_renewal", "n_risks",
                   "priority"]].copy()
    table["country"] = table["country"].map(COUNTRY_NAMES)
    open_sig = needs_decision(STATE)
    table["undecided"] = table["id"].map(open_sig[open_sig["kind"] == "risk"].groupby("account_id").size()).fillna(0).astype(int)
    view = STATE["assessment"]
    table["my_view"] = table["id"].map(view["rating"]) if not view.empty else None
    event = st.dataframe(table.drop(columns="id"), hide_index=True, width="stretch", on_select="rerun",
                         selection_mode="single-row", column_config={
                             "name": "Account", "country": "Country", "focus": "Problem area",
                             "health": st.column_config.ProgressColumn("Health", min_value=0, max_value=100, format="%.0f"),
                             "band": "Band",
                             "arr_eur": st.column_config.NumberColumn("ARR", format="euro"),
                             "days_to_renewal": st.column_config.NumberColumn("Renewal in", format="%d days"),
                             "n_risks": "Signals", "priority": st.column_config.NumberColumn("Priority", format="%.1f"),
                             "undecided": "Need decision", "my_view": "Your view",
                         })
    if event.selection.rows:
        open_account(table.iloc[event.selection.rows[0]]["id"])
    st.caption("Select a row to open the account.")

    for r in risky.itertuples():
        rs = account_signals(r.id, "risk")
        with st.container(border=True):
            head, btn = st.columns([5, 1])
            channel = f"via {r.partner}" if r.channel == "Partner" else "direct"
            head.markdown(f"### {r.name}\n{band_badge(r.band)} &nbsp; Health **{r.health:.0f}** · "
                          f"{COUNTRY_NAMES[r.country]} · {r.segment} · {eur(r.arr_eur)} ARR · "
                          f"renewal in {r.days_to_renewal} days · {channel}")
            open_button(btn, "Open account", f"radar-{r.id}", r.id)
            decide_button(btn, r.id, rs.loc[rs["status"] == "Needs decision", "rule_id"], f"decide-radar-{r.id}")
            for x in rs.itertuples():
                area = f" {area_badge(x.area)}" if x.area != "General" else ""
                st.markdown(f"{badge(x.severity.title(), *SEVERITY_BADGE[x.severity])}{area} **{x.title}**: {x.reason} "
                            f"&nbsp; {status_badge(x.status)}  \n:gray[Next step: {x.playbook}]")


def page_expansion():
    _, o = filtered()
    st.title("Expansion opportunities")
    st.caption("Usage and context that point to a next step. Readiness follows health: "
               "growth follows value, so unhealthy accounts get fixed first.")
    if o.empty:
        st.info("No opportunities for the selected regions.")
        return
    cols = st.columns(4)
    cols[0].metric("Total potential", eur(o["est_value_eur"].sum()), border=True)
    cols[1].metric("Ready now", eur(o.loc[o["readiness"] == READY, "est_value_eur"].sum()), border=True)
    cols[2].metric("Opportunities", len(o), border=True)
    cols[3].metric("Accounts", o["account_id"].nunique(), border=True)

    kinds = st.segmented_control("Type", ["Software", "Hardware", "Service"], selection_mode="multi",
                                 default=["Software", "Hardware", "Service"])
    o = o[o["kind"].isin(kinds or ["Software", "Hardware", "Service"])]
    if o.empty:
        st.info("No opportunities of this type.")
        return
    st.subheader("Potential by suggested module")
    by_mod = o.groupby(["module", "readiness"])["est_value_eur"].sum().reset_index()
    order = by_mod.groupby("module")["est_value_eur"].sum().sort_values().index.tolist()
    fig = go.Figure()
    for rd in [READY, CHECK, FIX]:
        g = by_mod[by_mod["readiness"] == rd].set_index("module").reindex(order).fillna(0)
        fig.add_bar(name=rd, y=order, x=g["est_value_eur"], orientation="h", marker_color=READINESS_COLORS[rd],
                    marker_line=dict(color=SURFACE, width=2),
                    hovertemplate="%{y} · " + rd + ": €%{x:,.0f}<extra></extra>")
    fig.update_layout(barmode="stack")
    fig.update_xaxes(tickprefix="€", tickformat="~s")
    st.plotly_chart(style(fig, height=300), width="stretch")

    choice = st.segmented_control("Show", [READY, CHECK, FIX, "All"], default="All")
    view = o if choice in (None, "All") else o[o["readiness"] == choice]
    for r in view.itertuples():
        with st.container(border=True):
            head, btn = st.columns([5, 1])
            head.markdown(f"### {r.account}: {r.module}\n"
                          f"{badge(r.readiness, *READINESS_BADGE[r.readiness])} &nbsp; **{eur(r.est_value_eur)}** per year "
                          f"(estimate) · {COUNTRY_NAMES[r.country]} · health {r.health:.0f}"
                          + (f" · via {r.partner}" if isinstance(r.partner, str) else ""))
            open_button(btn, "Open account", f"opp-{r.account_id}-{r.module_code}", r.account_id)
            es = account_signals(r.account_id, "expansion")
            es = es[es["rule_id"].isin(r.rule_ids)]
            decide_button(btn, r.account_id, es.loc[es["status"] == "Needs decision", "rule_id"],
                          f"decide-opp-{r.account_id}-{r.module_code}")
            head.markdown(" ".join(sorted({status_badge(x) for x in es["status"]})))
            for title, reason in zip(r.titles, r.reasons):
                st.markdown(f"- **{title}**: {reason}")
            st.markdown(f":gray[Next step: {r.playbooks[0]}]")
            with st.expander("Handover note for Sales"):
                st.code(sales_note(r._asdict(), DATA["metrics"][r.account_id]), language=None)


def page_account():
    s = DATA["summary"].sort_values("name")
    ids = s["id"].tolist()
    current = st.session_state.get("account_id", int(DATA["summary"].sort_values("priority", ascending=False)["id"].iloc[0]))
    acc_id = st.selectbox("Account", ids, index=ids.index(current),
                          format_func=lambda i: s.set_index("id").loc[i, "name"])
    st.session_state["account_id"] = acc_id
    a = s.set_index("id").loc[acc_id]
    m = DATA["metrics"][acc_id]
    channel = f"partner-led via {a['partner']}" if a["channel"] == "Partner" else "direct"
    st.title(a["name"])
    st.markdown(f"{band_badge(a['band'])} &nbsp; {COUNTRY_NAMES[a['country']]} · {a['segment']} · {a['tier']} · {channel}"
                + (f" &nbsp; Main problem area: {area_badge(a['focus'])}" if a["focus"] != "—" else "")
                + (f"  \n:violet[:material/bolt: Constrained grid: {m['grid_area']}]" if m["grid_area"] else ""))

    cols = st.columns(5)
    cols[0].metric("Health", f"{a['health']:.0f}", border=True)
    cols[1].metric("ARR", eur(a["arr_eur"]), f"{a['country_arr_share']:.0%} of {COUNTRY_NAMES[a['country']]}",
                   delta_color="off", delta_arrow="off", border=True)
    cols[2].metric("Renewal in", f"{a['days_to_renewal']} days", border=True)
    cols[3].metric("Active users", f"{m['active_users']:.0f} / {m['licensed_users']}",
                   f"{m['usage_change_pct']:+.0%} in 3 months" if m["usage_change_pct"] is not None else None,
                   border=True)
    cols[4].metric("Devices online", f"{m['devices_online']} / {m['devices_contracted']}", border=True)

    left, right = st.columns(2)
    with left:
        st.subheader("Health breakdown")
        parts = ["onboarding", "adoption", "outcomes", "relationship"]
        vals = [a[p] for p in parts]
        fig = go.Figure(go.Bar(y=[f"{p.title()} ({HEALTH_WEIGHTS[p]:.0%})" for p in parts][::-1], x=vals[::-1],
                               orientation="h", marker_color=SERIES[0], text=[f"{v:.0f}" for v in vals[::-1]],
                               textposition="outside", hovertemplate="%{y}: %{x:.0f}<extra></extra>"))
        fig.update_xaxes(range=[0, 108])
        st.plotly_chart(style(fig, height=240, legend=False), width="stretch")
    with right:
        st.subheader("Health over 26 weeks")
        h = DATA["health"][DATA["health"]["account_id"] == acc_id]
        fig = go.Figure(go.Scatter(x=h["as_of"], y=h["total"], mode="lines", line=dict(color=SERIES[0], width=2),
                                   hovertemplate="%{x}: %{y:.0f}<extra></extra>"))
        for lower, label, role in HEALTH_BANDS[:-1]:
            fig.add_hline(y=lower, line=dict(color=STATUS[role], width=1, dash="dot"),
                          annotation_text=label, annotation_position="top left",
                          annotation_font=dict(color=MUTED, size=11))
        fig.update_yaxes(range=[0, 100])
        st.plotly_chart(style(fig, height=240, legend=False), width="stretch")

    risks = account_signals(acc_id, "risk")
    exp = account_signals(acc_id, "expansion")
    opps = DATA["opportunities"]
    opps = opps[opps["account_id"] == acc_id] if not opps.empty else opps
    undecided = pd.concat([risks, exp])
    undecided = undecided.loc[undecided["status"] == "Needs decision", "rule_id"]
    head, btn = st.columns([5, 1])
    head.subheader("Signals")
    decide_button(btn, acc_id, undecided, f"decide-acc-{acc_id}", label=f"Decide ({len(undecided)})")
    left, right = st.columns(2)
    with left:
        st.markdown("**Risk**")
        if risks.empty:
            st.markdown(":green[No risk signals.]")
        for x in risks.itertuples():
            st.markdown(f"{badge(x.severity.title(), *SEVERITY_BADGE[x.severity])} **{x.title}**: {x.reason} "
                        f"&nbsp; {status_badge(x.status)}  \n:gray[Next step: {x.playbook}]")
    with right:
        st.markdown("**Expansion**")
        if opps.empty:
            st.markdown(":gray[No expansion signals.]")
        for x in opps.itertuples():
            statuses = " ".join(sorted({status_badge(v) for v in exp.loc[exp["rule_id"].isin(x.rule_ids), "status"]}))
            st.markdown(f"{badge(x.readiness, *READINESS_BADGE[x.readiness])} **{x.module}** ({eur(x.est_value_eur)}): "
                        + " ".join(x.reasons) + f" &nbsp; {statuses}")

    your_view(acc_id, a)

    st.subheader("Modules and usage")
    left, right = st.columns([2, 3])
    with left:
        mods = DATA["modules"].set_index("code")
        subs = DATA["subscriptions"][DATA["subscriptions"]["account_id"] == acc_id]
        rows = [{"Module": mods.loc[r.module_code, "name"], "Since": r.start_date,
                 "Active users": m["usage_by_module"].get(r.module_code),
                 "Licensed": r.licensed_users or None, "Annual value": r.annual_value_eur} for r in subs.itertuples()]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                     column_config={"Annual value": st.column_config.NumberColumn(format="euro")})
        st.markdown("**Security ladder**")
        ladder = [("OTC", "OT inventory"), ("OTC_VULN", "Vulnerability alerts"), ("OTC_PATCH", "Patch workflow"),
                  ("SIEM", "SIEM (detection)"), ("MDR", "Managed detection")]
        st.markdown(" → ".join(f":green[:material/check_circle: {n}]" if m[f"has_{c}"] else f":gray[:material/radio_button_unchecked: {n}]"
                               for c, n in ladder))
    with right:
        u = DATA["usage_weekly"][DATA["usage_weekly"]["account_id"] == acc_id]
        fig = go.Figure()
        for i, (code, g) in enumerate(u.groupby("module_code")):
            fig.add_scatter(x=g["week_start"], y=g["active_users"], mode="lines", name=mods.loc[code, "name"],
                            line=dict(color=SERIES[i % 4], width=2),
                            hovertemplate=code + " %{x}: %{y} users<extra></extra>")
        fig.update_layout(hovermode="x unified")
        fig.update_yaxes(title="Weekly active users", rangemode="tozero")
        st.plotly_chart(style(fig, height=300), width="stretch")

    module_outcomes(acc_id, m)

    st.subheader("Relationship")
    left, mid, right = st.columns(3)
    with left:
        st.markdown("**Contacts**")
        c = DATA["contacts"][DATA["contacts"]["account_id"] == acc_id]
        for x in c.itertuples():
            role = " · champion" if x.is_champion else (" · sponsor" if x.is_sponsor else "")
            gone = f" :red[(left {x.left_on})]" if isinstance(x.left_on, str) else ""
            chat = "" if isinstance(x.left_on, str) else f" · [Teams]({links.teams_chat([x.email], 'Hi ' + x.name.split()[0] + ',')})"
            st.markdown(f"{x.name}, {x.title}{role}{gone}{chat}")
    with mid:
        st.markdown("**Recent reviews**")
        r = DATA["reviews"][DATA["reviews"]["account_id"] == acc_id].sort_values("date", ascending=False).head(4)
        for x in r.itertuples():
            who = "with Siemens" if x.siemens_present else "partner only"
            obj = "objectives agreed" if x.objectives_documented else "no objectives"
            st.markdown(f"{x.date} · {x.kind} · {who} · {obj}")
    with right:
        st.markdown("**Support (last 90 days)**")
        t = DATA["tickets"][DATA["tickets"]["account_id"] == acc_id]
        t = t[t["opened_on"] > (AS_OF - timedelta(days=90)).isoformat()]
        st.markdown(f"{len(t)} tickets, {int(t['closed_on'].isna().sum())} open, "
                    f"{int(((t['priority'] == 'Critical') & t['closed_on'].isna()).sum())} critical open")
        if not t.empty:
            st.markdown(", ".join(f"{k} ({v})" for k, v in t["topic"].value_counts().head(3).items()))


def module_outcomes(acc_id, m):
    """One tab per subscribed module: OT Companion in depth, the others from the KPI catalog."""
    tabs = (["OTC"] if m["has_OTC"] else []) + [c for c in SOFTWARE if c != "OTC" and c in m["module_kpis"]]
    if not tabs:
        return
    st.subheader("Module outcomes")
    mods = DATA["modules"].set_index("code")
    health = m.get("module_health", {})
    labels = [f"{mods.loc[c, 'name'].split(':')[0]} · {health[c]:.0f}" if c in health else c for c in tabs]
    for code, tab in zip(tabs, st.tabs(labels)):
        with tab:
            if code == "OTC":
                otc_outcomes(acc_id, m)
                continue
            kpis = catalog.kpis_for(code)
            hist = DATA["module_kpi_weekly"]
            hist = hist[(hist["account_id"] == acc_id) & (hist["module_code"] == code)].sort_values("week_start")
            st.caption(mods.loc[code, "description"])
            cols = st.columns(len(kpis))
            for col, kpi in zip(cols, kpis):
                value = m["module_kpis"][code].get(kpi["id"])
                series = hist[hist["kpi"] == kpi["id"]]["value"].tail(26).tolist()
                ok = (catalog.score(kpi, value) or 0) >= 100
                col.metric(kpi["name"], catalog.fmt(kpi, value), f"target {catalog.fmt(kpi, kpi['target'])}",
                           delta_color="off", delta_arrow="off", border=True, chart_data=series, chart_type="line",
                           help=("On target" if ok else "Below target") + f" · score {catalog.score(kpi, value):.0f}/100")


def otc_outcomes(acc_id, m):
    cols = st.columns(5)
    cols[0].metric("Inventory coverage", f"{m['inventory_coverage']:.0%}",
                   f"{m['ot_assets_inventoried']} of ~{m['ot_assets_expected']} assets", delta_color="off",
                   delta_arrow="off", border=True)
    cols[1].metric("Critical CVEs open", m["crit_vulns_open"] if m["crit_vulns_open"] is not None else "n/a", border=True)
    cols[2].metric("Never acknowledged", m["crit_vulns_unack"] if m["crit_vulns_unack"] is not None else "n/a",
                   border=True)
    cols[3].metric("Mean time to patch", f"{m['mttp_days']:.0f} days" if m["mttp_days"] else "n/a", "target 30 days",
                   delta_color="off", delta_arrow="off", border=True)
    cols[4].metric("Patch tasks completed", f"{m['patch_completion']:.0%}" if m["patch_completion"] else "No workflow",
                   border=True)
    otc = DATA["otc_weekly"][DATA["otc_weekly"]["account_id"] == acc_id]
    if m["has_OTC_VULN"] and not otc.empty:
        fig = go.Figure()
        for col, name, color in [("crit_vulns_open", "Open critical CVEs", SERIES[0]),
                                 ("crit_vulns_unack", "Never acknowledged", SERIES[1])]:
            fig.add_scatter(x=otc["week_start"], y=otc[col], mode="lines", name=name,
                            line=dict(color=color, width=2), hovertemplate=name + " %{x}: %{y}<extra></extra>")
        fig.update_layout(hovermode="x unified")
        fig.update_yaxes(rangemode="tozero")
        st.plotly_chart(style(fig, height=260), width="stretch")


def page_coverage():
    s, _ = filtered()
    st.title("Coverage map")
    st.caption("Every account against every module: where the suite delivers, where it doesn't, and where the "
               "next module would fit. Numbers are module health (0–100) or the estimated value of an opportunity.")
    cov = coverage(DATA)
    cov = cov[cov["account_id"].isin(s["id"])]
    st.markdown(" ".join(f"{badge(k, c, i)}" for k, c, i in [
        ("Used well", "green", "check_circle"), ("Not delivering", "orange", "warning"),
        ("Opportunity", "blue", "add_circle"), ("Not used", "gray", "radio_button_unchecked"),
        ("Not relevant for this customer type", "gray", "remove")]))

    # Module penetration among customers the module fits.
    pen = []
    for code in SOFTWARE:
        c = cov[(cov["module_code"] == code) & (cov["state"] != "Not relevant")]
        used = c["state"].isin(["Used well", "Not delivering"]).sum()
        pen.append({"module": MODULE_SHORT[code], "used": used, "fit": len(c),
                    "share": used / len(c) if len(c) else 0, "open": (c["state"] == "Opportunity").sum()})
    pen = pd.DataFrame(pen)
    st.subheader("Who uses what")
    cov["label"] = cov.apply(lambda r: (f"{r.score:.0f}" if r.score == r.score and r.score is not None else "✓")
                             if r.state in ("Used well", "Not delivering") else
                             (f"+{eur(r.value)}" if r.state == "Opportunity" else
                              ("–" if r.state == "Not relevant" else "")), axis=1)
    grid = cov.pivot(index="account_id", columns="module_code", values="label")[SOFTWARE]
    states = cov.pivot(index="account_id", columns="module_code", values="state")[SOFTWARE]
    order = s.sort_values(["country", "arr_eur"], ascending=[True, False])
    order = order[order["id"].isin(grid.index)]
    grid, states = grid.loc[order["id"]], states.loc[order["id"]]
    grid.index = [f"{n} ({c})" for n, c in zip(order["name"], order["country"])]
    states.index = grid.index
    grid.columns = [MODULE_SHORT[c] for c in SOFTWARE]
    states.columns = grid.columns
    styled = grid.style.apply(lambda _: states.map(lambda v: f"background-color: {COVERAGE_STYLE[v]}; "
                                                             "color: #0b0b0b; text-align: center"), axis=None)
    st.dataframe(styled, width="stretch", height=35 * len(grid) + 40)
    left, right = st.columns(2)
    with left:
        st.subheader("Penetration")
        st.caption("Share of accounts that use a module, out of the accounts the module fits.")
        p = pen.sort_values("share")
        fig = go.Figure(go.Bar(y=p["module"], x=p["share"], orientation="h", marker_color=SERIES[0],
                               text=[f"{u} of {f}" for u, f in zip(p["used"], p["fit"])], textposition="outside",
                               hovertemplate="%{y}: %{x:.0%} of fitting accounts<extra></extra>"))
        fig.update_xaxes(tickformat=".0%", range=[0, 1.2])
        st.plotly_chart(style(fig, height=340, legend=False), width="stretch")
    with right:
        st.subheader("Signals by problem area")
        sig = STATE["signals"]
        sig = sig[sig["account_id"].isin(s["id"]) & sig["area"].isin(["Security", "Capacity", "Reliability"])]
        by = sig.groupby(["area", "kind"]).size().unstack(fill_value=0).reindex(["Security", "Capacity", "Reliability"]).fillna(0)
        fig = go.Figure()
        for kind, color in [("risk", STATUS["critical"]), ("expansion", SERIES[0])]:
            if kind in by:
                fig.add_bar(name=kind.title(), y=by.index, x=by[kind], orientation="h", marker_color=color,
                            marker_line=dict(color=SURFACE, width=2),
                            hovertemplate="%{y} · " + kind + ": %{x}<extra></extra>")
        fig.update_layout(barmode="stack")
        st.plotly_chart(style(fig, height=340), width="stretch")
        st.caption("Security dominates because OT Companion is the focus. Capacity signals cluster where the grid is "
                   "constrained, mostly in northern Norway.")


def your_view(acc_id, a):
    """The human side: own assessment, account plan, notes and a timeline of everything that happened."""
    st.subheader("Your view")
    current = STATE["assessment"].loc[acc_id] if not STATE["assessment"].empty and acc_id in STATE["assessment"].index else None
    if current is not None:
        differs = current["rating"] != a["band"]
        st.markdown(f"Data says {band_badge(a['band'])} ({a['health']:.0f}) · you say {band_badge(current['rating'])}"
                    + (" &nbsp; :orange[:material/compare_arrows: your view differs from the data]" if differs else "")
                    + f"  \n:gray[“{current['reason']}” ({current['written_on'][:10]})]")
    tab_view, tab_plan, tab_notes, tab_time = st.tabs(["Assessment", "Account plan", "Notes", "Timeline"])
    with tab_view:
        with st.form(f"assess-{acc_id}", clear_on_submit=True):
            options = journal.ASSESSMENTS
            default = options.index(current["rating"]) if current is not None else options.index(a["band"])
            rating = st.radio("How do you see this account?", options, index=default, horizontal=True)
            reason = st.text_input("Why? (what the data can't see)")
            if st.form_submit_button("Save assessment", type="primary"):
                journal.set_assessment(JCONN, acc_id, rating, reason)
                refresh()
        hist = STATE["assessments"]
        hist = hist[hist["account_id"] == acc_id] if not hist.empty else hist
        for x in hist.itertuples():
            st.markdown(f":gray[{x.written_on[:10]}] {band_badge(x.rating)} {x.reason or ''}")
    with tab_plan:
        plan = STATE["plans"].get(acc_id, {})
        with st.form(f"plan-{acc_id}"):
            objectives = st.text_area("Objectives agreed with the customer", plan.get("objectives") or "", height=120)
            strategy = st.text_area("Your strategy for the account", plan.get("strategy") or "", height=100)
            if st.form_submit_button("Save plan", type="primary"):
                journal.save_plan(JCONN, acc_id, objectives, strategy)
                refresh()
        if plan:
            st.caption(f"Last updated {plan['updated_on']}")
    with tab_notes:
        with st.form(f"note-{acc_id}", clear_on_submit=True):
            text = st.text_area("Add a note", placeholder="Something you heard, a change at the customer, a gut feeling…")
            if st.form_submit_button("Add note", type="primary") and text.strip():
                journal.add_note(JCONN, acc_id, text.strip())
                refresh()
        notes = STATE["notes"]
        notes = notes[notes["account_id"] == acc_id] if not notes.empty else notes
        for x in notes.itertuples():
            st.markdown(f":gray[{x.written_on[:10]}] {x.text}")
    with tab_time:
        events = []
        dec = STATE["decisions"]
        for d in (dec[dec["account_id"] == acc_id].itertuples() if not dec.empty else []):
            covers = ", ".join(RULES[r]["title"] for r in d.rule_ids.split(",") if r in RULES)
            events.append((d.created_on, "gavel", f"Decided **{d.decision}** for: {covers}"
                           + (f". {d.note}" if isinstance(d.note, str) and d.note and d.status != "done" else "")))
            if d.status == "done":
                events.append((d.completed_on, "task_alt", f"**{d.decision}** done → **{d.outcome}**"
                               + (f". {d.note}" if isinstance(d.note, str) and d.note else "")))
            elif d.status == "cancelled":
                events.append((d.completed_on, "cancel", f"**{d.decision}** cancelled"))
        notes = STATE["notes"]
        for x in (notes[notes["account_id"] == acc_id].itertuples() if not notes.empty else []):
            events.append((x.written_on[:10], "edit_note", f"Note: {x.text}"))
        hist = STATE["assessments"]
        for x in (hist[hist["account_id"] == acc_id].itertuples() if not hist.empty else []):
            events.append((x.written_on[:10], "person", f"Your assessment: **{x.rating}**. {x.reason or ''}"))
        for x in DATA["reviews"][DATA["reviews"]["account_id"] == acc_id].sort_values("date").tail(3).itertuples():
            events.append((x.date, "groups", f"{x.kind} ({'with Siemens' if x.siemens_present else 'partner only'})"))
        if not events:
            st.caption("Nothing yet.")
        for day, icon, text in sorted(events, key=lambda e: e[0], reverse=True):
            st.markdown(f":gray[{day}] &nbsp; :material/{icon}: {text}")


def page_actions():
    s, _ = filtered()
    st.title("Action center")
    st.caption("The radar flags, you decide. Every signal gets a decision: act, monitor until a date, or dismiss "
               "with a reason. Results feed back into the account's signals.")
    nd = needs_decision(STATE)
    nd = nd[nd["account_id"].isin(s["id"])]
    dec = STATE["decisions"]
    dec = dec[dec["account_id"].isin(s["id"])] if not dec.empty else dec
    open_ = dec[dec["status"] == "open"].sort_values("due_on") if not dec.empty else dec
    overdue = open_[open_["due_on"] < TODAY.isoformat()] if not open_.empty else open_
    done30 = dec[(dec["status"] == "done") & (dec["completed_on"] >= (TODAY - timedelta(days=30)).isoformat())] \
        if not dec.empty else dec
    cols = st.columns(4)
    cols[0].metric("Signals needing a decision", len(nd), f"on {nd['account_id'].nunique()} accounts",
                   delta_color="off", delta_arrow="off", border=True)
    cols[1].metric("Open actions", len(open_), border=True)
    cols[2].metric("Overdue", len(overdue), border=True)
    cols[3].metric("Done in the last 30 days", len(done30), border=True)

    t1, t2, t3, t4 = st.tabs([f"Needs decision ({nd['account_id'].nunique()})", f"Open actions ({len(open_)})",
                              "History", "Did it help?"])
    with t1:
        order = s.set_index("id")["priority"]
        accounts = sorted(nd["account_id"].unique(), key=lambda i: (-order.get(i, 0), account_name(i)))
        for acc_id in accounts:
            a = s.set_index("id").loc[acc_id]
            sig = nd[nd["account_id"] == acc_id].assign(o=lambda d: d["severity"].map(SEV_ORDER)).sort_values("o")
            with st.container(border=True):
                head, btn = st.columns([5, 1])
                head.markdown(f"**{a['name']}** · {COUNTRY_NAMES[a['country']]} · {eur(a['arr_eur'])} &nbsp; "
                              f"{band_badge(a['band'])}")
                decide_button(btn, acc_id, sig["rule_id"], f"decide-ac-{acc_id}")
                open_button(btn, "Open account", f"open-ac-{acc_id}", acc_id)
                for x in sig.itertuples():
                    kind = badge("Expansion", "green", "trending_up") if x.kind == "expansion" else \
                        badge(x.severity.title(), *SEVERITY_BADGE[x.severity])
                    head.markdown(f"{kind} **{x.title}**: {x.reason} :gray[· suggested: {x.suggested_action}]")
    with t2:
        if open_.empty:
            st.caption("No open actions.")
        for d in open_.to_dict("records"):
            action_card(clean(d), d["id"])
    with t3:
        hist = dec[dec["status"] != "open"].copy() if not dec.empty else dec
        if hist.empty:
            st.caption("No history yet.")
        else:
            hist["when"] = hist["completed_on"].fillna(hist["created_on"])
            hist["covers"] = hist["rule_ids"].map(lambda r: ", ".join(RULES[x]["title"] for x in r.split(",") if x in RULES))
            st.dataframe(hist.sort_values("when", ascending=False)[["when", "account", "decision", "status", "outcome",
                                                                     "covers", "note"]],
                         hide_index=True, width="stretch",
                         column_config={"when": "Date", "account": "Account", "decision": "Decision",
                                        "status": "Status", "outcome": "Outcome", "covers": "Signals", "note": "Note"})
    with t4:
        eff = effectiveness(STATE, DATA)
        if eff.empty:
            st.caption("Not enough completed actions yet.")
        else:
            st.markdown("Which actions tend to work? Based on the outcome you logged for each completed action.")
            eff = eff.sort_values("helped")
            fig = go.Figure(go.Bar(y=eff["decision"], x=eff["helped"], orientation="h", marker_color=SERIES[0],
                                   text=[f"{h:.0%} of {n}" for h, n in zip(eff["helped"], eff["actions"])],
                                   textposition="outside",
                                   hovertemplate="%{y}: %{x:.0%} solved or improved<extra></extra>"))
            fig.update_xaxes(tickformat=".0%", range=[0, 1.15], title="Share solved or improved")
            st.plotly_chart(style(fig, height=320, legend=False), width="stretch")
            st.dataframe(eff.sort_values("helped", ascending=False), hide_index=True, width="stretch", column_config={
                "decision": "Action", "actions": "Completed",
                "helped": st.column_config.NumberColumn("Solved or improved", format="percent"),
                "health_change": st.column_config.NumberColumn("Health change after 4 weeks", format="%+.1f"),
            })
            st.caption("With real data, comparing your logged outcome with the measured health change shows whether "
                       "an action really moved the account. In this prototype the health history is synthetic and "
                       "doesn't react to actions, so that column is only illustrative.")


def page_method():
    st.title("How it works")
    st.caption("A prototype on synthetic data. The logic is meant to plug into the systems Siemens already runs.")
    st.graphviz_chart("""
    digraph {
      rankdir=LR; bgcolor="transparent";
      node [shape=box, style="rounded,filled", fillcolor="#f0efec", color="#c3c2b7", fontname="Helvetica", fontsize=11];
      edge [color="#898781"];
      subgraph cluster_s { label="Sources (assumed)"; fontname="Helvetica"; color="#e1e0d9";
        crm [label="CRM\\n(Salesforce)"]; sub [label="Subscription Manager"]; plat [label="Platform telemetry\\n(tenant, SiemensID)"];
        otc [label="OT Companion data"]; sup [label="Support desk"]; reg [label="Regulation\\n(maintained by hand)"]; }
      db [label="SQLite\\nsource tables", fillcolor="#cde2fb"];
      met [label="Metrics\\nper account"]; hs [label="Health score\\n4 parts"]; rules [label="Rules\\n(rules.toml)"];
      out [label="Dashboard\\n+ playbooks", fillcolor="#cde2fb"];
      {crm sub plat otc sup reg} -> db -> met; met -> hs -> rules; met -> rules -> out;
    }""")

    st.subheader("Where the data would come from")
    st.markdown("Which system holds what at Siemens SI EA is an **assumption** to verify. The prototype's tables "
                "mirror what each source would deliver, so swapping synthetic data for real extracts doesn't change the logic.")
    sources = pd.DataFrame([
        ("CRM (likely Salesforce)", "accounts, contacts, reviews", "Renewal date, sponsor, champion, review dates, objectives"),
        ("Subscription Manager", "subscriptions, subscription_events", "ARR, modules, add-ons, contracted devices, downgrades"),
        ("Platform: tenant", "devices, usage_weekly", "Connected Devices online, active sites"),
        ("Platform: SiemensID", "usage_weekly", "Active users, logins, activity of the busiest user"),
        ("OT Companion", "otc_weekly", "Inventory coverage, CVEs, acknowledgements, time to patch, patch tasks"),
        ("Support desk", "tickets", "Ticket volume, priority, open critical tickets"),
        ("Survey tool", "surveys", "NPS"),
        ("Hand-maintained", "regions", "NIS2 status per country, market notes"),
    ], columns=["Source", "Tables", "What it provides"])
    st.dataframe(sources, hide_index=True, width="stretch")

    st.subheader("Health score")
    w = HEALTH_WEIGHTS
    st.markdown(
        f"Four parts, each 0–100: **onboarding** {w['onboarding']:.0%} (devices online vs. contracted), "
        f"**adoption** {w['adoption']:.0%} (licence use, usage trend, dependence on one user), "
        f"**outcomes** {w['outcomes']:.0%} (alerts acknowledged; for OT Companion also inventory coverage, "
        f"unacknowledged CVEs and time to patch) and **relationship** {w['relationship']:.0%} "
        f"(review recency, sponsor, support load, NPS, agreed objectives).  \n"
        f"The total is the weighted average, but at most **{WEAKEST_PART_MARGIN} points above the weakest part**, "
        f"so a strong relationship can't hide a broken onboarding.  \n"
        "Bands: " + " · ".join(f"{band_badge(label)} from {lower}" for lower, label, _ in HEALTH_BANDS))

    st.subheader("From signal to action")
    st.markdown(
        "The radar only flags. **You decide** what to do with each signal: call, visit, review, training, "
        "escalate, involve Sales, go through the partner, **monitor** until a date, or **dismiss** with a reason. "
        "A decision keeps the signal quiet while the action is open, until the monitoring date, or for "
        f"{journal.DISMISS_DAYS} days after a dismissal. {journal.AFTER_DONE_DAYS} days after an action is done, the "
        "signal comes back if the problem is still there.  \n"
        "Completed calls, visits, reviews and trainings count as **direct contact** and update the metrics, so a "
        "logged call can clear the 'no direct view' signal.  \n"
        "Your **own assessment, account plan and notes** sit next to the data. When your view differs from the "
        "health score, the account page says so: that's often where the interesting conversations are.")
    st.markdown(
        "**Where it would live in production:** decisions and actions as Salesforce tasks (so Sales and account "
        "management see them), emails and meetings in Outlook and Teams. In the prototype, email, Teams and calendar "
        "links work as they are, and the Salesforce task is shown as a preview. Your input is stored in "
        "`data/journal.db`, separate from the generated data.")

    st.subheader("Rules")
    st.markdown("Every signal comes from a readable rule in `csm/rules.toml`. No black box: "
                "the reason shown on each signal is the rule's own explanation.")
    rules = pd.DataFrame([{
        "ID": r["id"], "Type": r["kind"].title(), "Signal": r["title"], "Severity": r["severity"],
        "Fires when": " and ".join(f"{a} {op} {v}" for a, op, v in r["when"]),
        "Suggests": r.get("module", ""), "Suggested action": r.get("action", ""),
    } for r in load_rules()])
    st.dataframe(rules, hide_index=True, width="stretch")

    st.subheader("Module catalog")
    st.markdown("Each module's outcome KPIs, targets and direction come from `csm/catalog.toml`. A module's health is "
                "the average KPI score; a KPI at target scores 100, at half the target (or double, for 'lower is "
                "better') it scores 0. OT Companion has its own, more detailed data. The account's outcome score "
                "is half the ARR-weighted module average and half the weakest module.")
    mods = DATA["modules"].set_index("code")
    st.dataframe(pd.DataFrame([{"Module": mods.loc[k["module"], "name"], "KPI": k["name"],
                                "Target": catalog.fmt(k, k["target"]),
                                "Better": k["better"]} for k in catalog.kpis()]), hide_index=True, width="stretch")
    st.markdown("Expansion also covers **hardware and services** that software use pulls through: gateways, grid "
                "sensors and smart fuses, fault sensor indicators, load management controllers, installation help "
                "and OT security assessments.")

    st.subheader("Metrics")
    st.dataframe(pd.DataFrame([(k, src, desc) for k, (src, desc) in METRIC_DOCS.items()],
                              columns=["Metric", "Source", "Meaning"]), hide_index=True, width="stretch")
    st.caption("All companies, people, prices and figures are fictional. Module structure follows public "
               "Electrification X product information; prices are placeholders.")


PAGES = {
    "portfolio": st.Page(page_portfolio, title="Portfolio", icon=":material/dashboard:", url_path="portfolio", default=True),
    "actions": st.Page(page_actions, title="Action center", icon=":material/task_alt:", url_path="actions"),
    "regions": st.Page(page_regions, title="Regions", icon=":material/public:", url_path="regions"),
    "risk": st.Page(page_risk, title="Risk radar", icon=":material/warning:", url_path="risk"),
    "expansion": st.Page(page_expansion, title="Expansion", icon=":material/trending_up:", url_path="expansion"),
    "coverage": st.Page(page_coverage, title="Coverage map", icon=":material/grid_view:", url_path="coverage"),
    "account": st.Page(page_account, title="Account detail", icon=":material/apartment:", url_path="account"),
    "method": st.Page(page_method, title="How it works", icon=":material/schema:", url_path="how-it-works"),
}

with st.sidebar:
    st.markdown("### Nordic CS Radar")
    st.caption("Electrification X · OT Companion focus · prototype")
    st.pills("Regions", list(COUNTRY_NAMES), format_func=COUNTRY_NAMES.get, selection_mode="multi",
             default=list(COUNTRY_NAMES), key="countries")
    st.caption(f"Data as of {AS_OF:%d %b %Y}. Synthetic, fictional accounts.")

st.navigation(list(PAGES.values())).run()
