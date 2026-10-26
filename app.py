"""Nordic Customer Success Radar: Streamlit dashboard.

Run:  streamlit run app.py
"""

from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from csm import generate, pipeline
from csm.config import AS_OF, HEALTH_BANDS, HEALTH_WEIGHTS, WEAKEST_PART_MARGIN
from csm.db import DB_PATH, connect
from csm.metrics import METRIC_DOCS
from csm.signals import load_rules
from csm.views import CHECK, FIX, READY, load, region_summary, sales_note

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


def badge(label, color, icon):
    return f":{color}-badge[:material/{icon}: {label}]"


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


# --- Data ------------------------------------------------------------------------
@st.cache_data
def get_data(db_mtime):
    conn = connect()
    data = load(conn)
    conn.close()
    return data


if not DB_PATH.exists():
    with st.spinner("Generating synthetic portfolio…"):
        generate.build().close()
        pipeline.analyse(connect())
DATA = get_data(DB_PATH.stat().st_mtime)


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
                b.button("Open", key=f"risk-{r.id}", on_click=open_account, args=(r.id,), width="stretch")
    with right:
        st.subheader("Top expansion opportunities")
        for r in (ready.head(6).itertuples() if not ready.empty else []):
            with st.container(border=True):
                a, b = st.columns([4, 1])
                a.markdown(f"**{r.account}** · {COUNTRY_NAMES[r.country]} · **{eur(r.est_value_eur)}**  \n"
                           f"{r.module}: {r.reasons[0]}")
                b.button("Open", key=f"exp-{r.account_id}-{r.module_code}", on_click=open_account,
                         args=(r.account_id,), width="stretch")


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
    sig = DATA["signals"]
    sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}

    table = risky[["id", "name", "country", "health", "band", "arr_eur", "days_to_renewal", "n_risks", "priority"]].copy()
    table["country"] = table["country"].map(COUNTRY_NAMES)
    event = st.dataframe(table.drop(columns="id"), hide_index=True, width="stretch", on_select="rerun",
                         selection_mode="single-row", column_config={
                             "name": "Account", "country": "Country",
                             "health": st.column_config.ProgressColumn("Health", min_value=0, max_value=100, format="%.0f"),
                             "band": "Band",
                             "arr_eur": st.column_config.NumberColumn("ARR", format="euro"),
                             "days_to_renewal": st.column_config.NumberColumn("Renewal in", format="%d days"),
                             "n_risks": "Signals", "priority": st.column_config.NumberColumn("Priority", format="%.1f"),
                         })
    if event.selection.rows:
        open_account(table.iloc[event.selection.rows[0]]["id"])
    st.caption("Select a row to open the account.")

    for r in risky.itertuples():
        rs = sig[(sig["account_id"] == r.id) & (sig["kind"] == "risk")].copy()
        rs["o"] = rs["severity"].map(sev_order)
        with st.container(border=True):
            head, btn = st.columns([5, 1])
            channel = f"via {r.partner}" if r.channel == "Partner" else "direct"
            head.markdown(f"### {r.name}\n{band_badge(r.band)} &nbsp; Health **{r.health:.0f}** · "
                          f"{COUNTRY_NAMES[r.country]} · {r.segment} · {eur(r.arr_eur)} ARR · "
                          f"renewal in {r.days_to_renewal} days · {channel}")
            btn.button("Open account", key=f"radar-{r.id}", on_click=open_account, args=(r.id,), width="stretch")
            for x in rs.sort_values("o").itertuples():
                st.markdown(f"{badge(x.severity.title(), *SEVERITY_BADGE[x.severity])} **{x.title}**: {x.reason}  \n"
                            f":gray[Next step: {x.playbook}]")


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
            btn.button("Open account", key=f"opp-{r.account_id}-{r.module_code}", on_click=open_account,
                       args=(r.account_id,), width="stretch")
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
    st.markdown(f"{band_badge(a['band'])} &nbsp; {COUNTRY_NAMES[a['country']]} · {a['segment']} · {a['tier']} · {channel}")

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

    risks = DATA["signals"][(DATA["signals"]["account_id"] == acc_id) & (DATA["signals"]["kind"] == "risk")]
    opps = DATA["opportunities"]
    opps = opps[opps["account_id"] == acc_id] if not opps.empty else opps
    left, right = st.columns(2)
    with left:
        st.subheader("Risk signals")
        if risks.empty:
            st.markdown(":green[No risk signals.]")
        for x in risks.itertuples():
            st.markdown(f"{badge(x.severity.title(), *SEVERITY_BADGE[x.severity])} **{x.title}**: {x.reason}  \n"
                        f":gray[Next step: {x.playbook}]")
    with right:
        st.subheader("Expansion signals")
        if opps.empty:
            st.markdown(":gray[No expansion signals.]")
        for x in opps.itertuples():
            st.markdown(f"{badge(x.readiness, *READINESS_BADGE[x.readiness])} **{x.module}** ({eur(x.est_value_eur)}): "
                        + " ".join(x.reasons))

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

    if m["has_OTC"]:
        st.subheader("OT Companion outcomes")
        cols = st.columns(5)
        cols[0].metric("Inventory coverage", f"{m['inventory_coverage']:.0%}",
                       f"{m['ot_assets_inventoried']} of ~{m['ot_assets_expected']} assets", delta_color="off", delta_arrow="off", border=True)
        cols[1].metric("Critical CVEs open", m["crit_vulns_open"] if m["crit_vulns_open"] is not None else "n/a", border=True)
        cols[2].metric("Never acknowledged", m["crit_vulns_unack"] if m["crit_vulns_unack"] is not None else "n/a", border=True)
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

    st.subheader("Relationship")
    left, mid, right = st.columns(3)
    with left:
        st.markdown("**Contacts**")
        c = DATA["contacts"][DATA["contacts"]["account_id"] == acc_id]
        for x in c.itertuples():
            role = " · champion" if x.is_champion else (" · sponsor" if x.is_sponsor else "")
            gone = f" :red[(left {x.left_on})]" if x.left_on else ""
            st.markdown(f"{x.name}, {x.title}{role}{gone}")
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

    st.subheader("Rules")
    st.markdown("Every signal comes from a readable rule in `csm/rules.toml`. No black box: "
                "the reason shown on each signal is the rule's own explanation.")
    rules = pd.DataFrame([{
        "ID": r["id"], "Type": r["kind"].title(), "Signal": r["title"], "Severity": r["severity"],
        "Fires when": " and ".join(f"{a} {op} {v}" for a, op, v in r["when"]),
        "Suggests": r.get("module", ""),
    } for r in load_rules()])
    st.dataframe(rules, hide_index=True, width="stretch")

    st.subheader("Metrics")
    st.dataframe(pd.DataFrame([(k, src, desc) for k, (src, desc) in METRIC_DOCS.items()],
                              columns=["Metric", "Source", "Meaning"]), hide_index=True, width="stretch")
    st.caption("All companies, people, prices and figures are fictional. Module structure follows public "
               "Electrification X product information; prices are placeholders.")


PAGES = {
    "portfolio": st.Page(page_portfolio, title="Portfolio", icon=":material/dashboard:", url_path="portfolio", default=True),
    "regions": st.Page(page_regions, title="Regions", icon=":material/public:", url_path="regions"),
    "risk": st.Page(page_risk, title="Risk radar", icon=":material/warning:", url_path="risk"),
    "expansion": st.Page(page_expansion, title="Expansion", icon=":material/trending_up:", url_path="expansion"),
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
