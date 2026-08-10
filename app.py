"""
WeGro IR Daily Dashboard
-------------------------
Streamlit app that ingests the IR team's manually-maintained daily tracking
excel (one row per day) and renders a funnel + trend dashboard.

Run locally:
    pip install -r requirements.txt
    streamlit run app.py
"""

import io
import copy
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, Table, TableStyle,
)

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

st.set_page_config(
    page_title="WeGro IR Daily Dashboard",
    page_icon="📊",
    layout="wide",
)

# Expected columns from the IR team's daily tracking sheet.
# Keys = canonical internal name, Values = possible header text variants
# (IR team's manual sheet formatting can drift, so we match loosely).
EXPECTED_COLUMNS = {
    "day": ["day"],
    "registrations": ["number of registration (interest)", "number of registration", "registration"],
    "tickets_booked": ["number of tickets booked (consideration)", "tickets booked"],
    "tickets_invested": ["number of tickets invested", "tickets invested"],
    "unique_investors": ["number of unique investors", "unique investors"],
    "new_investors": ["number of new unique investors", "new unique investors"],
    "old_investors": ["number of old unique investors", "old unique investors"],
    "investment_value": ["investment in value (payment)", "investment in value", "investment value"],
    "payables": ["payables"],
}


# --------------------------------------------------------------------------
# Data loading & cleaning
# --------------------------------------------------------------------------

def normalize_header(col: str) -> str:
    return str(col).strip().lower()


def map_columns(df: pd.DataFrame) -> dict:
    """Map actual sheet headers to canonical internal names."""
    normalized = {normalize_header(c): c for c in df.columns}
    mapping = {}
    for canonical, variants in EXPECTED_COLUMNS.items():
        for variant in variants:
            if variant in normalized:
                mapping[canonical] = normalized[variant]
                break
    return mapping


@st.cache_data(show_spinner=False)
def load_raw(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """Load a file with NO header assumption - every row (including any
    section labels like 'Cumulative' above the real header) becomes a data
    row. We detect the real header row separately, since manually-built
    sheets sometimes have a label row above the actual column names."""
    if filename.lower().endswith(".csv"):
        for encoding in ["utf-8", "utf-8-sig", "latin1"]:
            try:
                return pd.read_csv(io.BytesIO(file_bytes), header=None, encoding=encoding)
            except UnicodeDecodeError:
                continue
        raise ValueError("Could not decode the CSV file with common encodings (utf-8, latin1).")
    return pd.read_excel(io.BytesIO(file_bytes), header=None)


def detect_header_row(raw_df: pd.DataFrame, max_scan: int = 10) -> int:
    """Scan the first `max_scan` rows and return the index of the row that
    best matches our known column headers (e.g. contains 'day', 'registration',
    etc). Falls back to row 0 if nothing matches well."""
    all_known_variants = [v for variants in EXPECTED_COLUMNS.values() for v in variants]

    best_row, best_score = 0, -1
    for i in range(min(max_scan, len(raw_df))):
        row_values = [normalize_header(v) for v in raw_df.iloc[i].tolist()]
        score = sum(1 for val in row_values if val in all_known_variants)
        if score > best_score:
            best_row, best_score = i, score

    return best_row


def build_dataframe(raw_df: pd.DataFrame, header_row: int) -> pd.DataFrame:
    """Slice a headerless dataframe into a proper dataframe using the given
    row index as the header. Drops fully-empty trailing columns (common
    Excel artifact) and de-duplicates any remaining blank/duplicate headers
    so downstream display (st.dataframe) never sees duplicate column names.

    Works positionally (iloc) throughout, since the raw header row can
    contain multiple blank/NaN entries - selecting by label in that case
    would return a DataFrame instead of a Series (ambiguous truth value)."""
    header_values = raw_df.iloc[header_row].tolist()
    data = raw_df.iloc[header_row + 1:].copy()
    data = data.reset_index(drop=True)

    # Decide which column positions to keep - drop columns with no header
    # AND no data at all (blank trailing columns left over from Excel).
    keep_positions = []
    for pos in range(data.shape[1]):
        header_val = header_values[pos]
        header_is_blank = pd.isna(header_val) or str(header_val).strip() == ""
        column_is_empty = data.iloc[:, pos].isna().all()
        if header_is_blank and column_is_empty:
            continue
        keep_positions.append(pos)

    data = data.iloc[:, keep_positions]
    kept_headers = [header_values[pos] for pos in keep_positions]

    # De-duplicate any remaining blank or repeated headers (e.g. a blank
    # column that does have stray data, or two columns with the same name)
    # so pandas/Streamlit never see duplicate column labels.
    seen = {}
    new_columns = []
    for header_val in kept_headers:
        label = "Unnamed" if (pd.isna(header_val) or str(header_val).strip() == "") else str(header_val)
        if label in seen:
            seen[label] += 1
            label = f"{label}_{seen[label]}"
        else:
            seen[label] = 0
        new_columns.append(label)
    data.columns = new_columns

    return data


def clean_data(df: pd.DataFrame, col_map: dict) -> pd.DataFrame:
    """Rename to canonical columns, parse dates, coerce numerics, drop empty rows."""
    rename_dict = {v: k for k, v in col_map.items()}
    df = df.rename(columns=rename_dict)

    if "day" not in df.columns:
        raise ValueError(
            "Could not find a 'Day' column in the uploaded file. "
            "Please check the sheet has a column named 'Day'."
        )

    # Parse dates - primary format matches the IR team's sheet: "01-Aug-26"
    raw_day_values = df["day"].copy()
    df["day"] = pd.to_datetime(df["day"], format="%d-%b-%y", errors="coerce")
    # Fallback for rows that don't match the expected format (e.g. manual edits)
    still_missing = df["day"].isna()
    if still_missing.any():
        df.loc[still_missing, "day"] = pd.to_datetime(
            raw_day_values[still_missing], errors="coerce", dayfirst=True
        )
    df = df.dropna(subset=["day"])

    numeric_cols = [
        "registrations", "tickets_booked", "tickets_invested",
        "unique_investors", "new_investors", "old_investors",
        "investment_value", "payables",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Keep only the columns the dashboard actually knows about - anything
    # else in the sheet (target tables, stray notes, extra columns) is
    # dropped here rather than silently carried through to charts/tables.
    known_columns = ["day"] + numeric_cols
    df = df[[c for c in known_columns if c in df.columns]]

    df = df.sort_values("day").reset_index(drop=True)
    return df


# --------------------------------------------------------------------------
# Chart builders
# --------------------------------------------------------------------------

def kpi_row(df: pd.DataFrame) -> dict:
    """Renders the KPI metric row and returns the computed values as a
    dict, so the same numbers can be reused in the PDF export without
    recalculating them."""
    total_reg = df.get("registrations", pd.Series(dtype=float)).sum()
    total_booked = df.get("tickets_booked", pd.Series(dtype=float)).sum()
    total_invested = df.get("tickets_invested", pd.Series(dtype=float)).sum()
    total_value = df.get("investment_value", pd.Series(dtype=float)).sum()
    total_unique = df.get("unique_investors", pd.Series(dtype=float)).sum()
    total_new = df.get("new_investors", pd.Series(dtype=float)).sum()

    conversion_rate = (total_invested / total_reg * 100) if total_reg else 0
    new_investor_pct = (total_new / total_unique * 100) if total_unique else 0

    cols = st.columns(6)
    cols[0].metric("Total Registrations", f"{total_reg:,.0f}")
    cols[1].metric("Tickets Booked", f"{total_booked:,.0f}")
    cols[2].metric("Tickets Invested", f"{total_invested:,.0f}")
    cols[3].metric("Investment Value", f"Tk {total_value:,.0f}")
    cols[4].metric("Reg → Invested Conv.", f"{conversion_rate:.1f}%")
    cols[5].metric("New Investor Mix", f"{new_investor_pct:.1f}%")

    return {
        "Total Registrations": f"{total_reg:,.0f}",
        "Tickets Booked": f"{total_booked:,.0f}",
        "Tickets Invested": f"{total_invested:,.0f}",
        "Investment Value": f"Tk {total_value:,.0f}",
        "Reg → Invested Conversion": f"{conversion_rate:.1f}%",
        "New Investor Mix": f"{new_investor_pct:.1f}%",
    }


def funnel_chart(df: pd.DataFrame):
    stages = ["Registration (Interest)", "Tickets Booked (Consideration)", "Tickets Invested (Conversion)"]
    values = [
        df.get("registrations", pd.Series(dtype=float)).sum(),
        df.get("tickets_booked", pd.Series(dtype=float)).sum(),
        df.get("tickets_invested", pd.Series(dtype=float)).sum(),
    ]
    fig = go.Figure(go.Funnel(
        y=stages,
        x=values,
        textinfo="value+percent initial",
        marker={"color": ["#4C72B0", "#55A868", "#C44E52"]},
    ))
    fig.update_layout(title="Investor Funnel (Period Total)", height=380)
    return fig


def trend_chart(df: pd.DataFrame):
    fig = go.Figure()
    for col, label, color in [
        ("registrations", "Registrations", "#4C72B0"),
        ("tickets_booked", "Tickets Booked", "#55A868"),
        ("tickets_invested", "Tickets Invested", "#C44E52"),
    ]:
        if col in df.columns:
            fig.add_trace(go.Scatter(x=df["day"], y=df[col], mode="lines+markers", name=label, line=dict(color=color)))
    fig.update_layout(title="Daily Funnel Trend", xaxis_title="Day", yaxis_title="Count", height=400)
    return fig


def investor_mix_chart(df: pd.DataFrame):
    if "new_investors" not in df.columns or "old_investors" not in df.columns:
        return None
    fig = go.Figure()
    fig.add_trace(go.Bar(x=df["day"], y=df["new_investors"], name="New Investors", marker_color="#55A868"))
    fig.add_trace(go.Bar(x=df["day"], y=df["old_investors"], name="Old Investors", marker_color="#8C8C8C"))
    fig.update_layout(barmode="stack", title="New vs Old Unique Investors (Daily)", height=380)
    return fig


def investor_mix_donut(df: pd.DataFrame):
    """Period-total New vs Old investor split as a donut chart. Valid pie
    chart candidate since New + Old are mutually exclusive and sum to the
    whole (Unique Investors) - unlike the funnel stages, which overlap.
    The Unique Investors total is shown as text in the donut's center
    hole, since it's the sum of the two slices, not a third slice itself."""
    if "new_investors" not in df.columns or "old_investors" not in df.columns:
        return None
    total_new = df["new_investors"].sum()
    total_old = df["old_investors"].sum()
    total_unique = total_new + total_old
    if total_unique == 0:
        return None
    fig = go.Figure(go.Pie(
        labels=["New Investors", "Old Investors"],
        values=[total_new, total_old],
        hole=0.5,
        marker=dict(colors=["#55A868", "#8C8C8C"]),
        textinfo="label+percent+value",
        domain=dict(x=[0, 1], y=[0, 0.82]),  # reserve top ~18% so outside labels never collide with the title
    ))
    fig.update_layout(
        title=dict(text="New vs Old Investor Mix (Period Total)", y=0.98, yanchor="top"),
        height=440,
        margin=dict(t=70, b=30),
        annotations=[dict(
            text=f"{total_unique:,.0f}<br>Total",
            x=0.5, y=0.41,
            font_size=20,
            showarrow=False,
        )],
    )
    return fig


def investment_vs_target_chart(df: pd.DataFrame, monthly_target: float):
    if "investment_value" not in df.columns:
        return None
    df = df.copy()
    df["cumulative_value"] = df["investment_value"].fillna(0).cumsum()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["day"], y=df["cumulative_value"], mode="lines+markers",
        name="Cumulative Investment Value", line=dict(color="#4C72B0"),
        fill="tozeroy",
    ))
    if monthly_target > 0:
        fig.add_hline(
            y=monthly_target, line_dash="dash", line_color="red",
            annotation_text=f"Target: Tk {monthly_target:,.0f}", annotation_position="top left",
        )
    fig.update_layout(title="Cumulative Investment Value vs Monthly Target", xaxis_title="Day", yaxis_title="Value (Tk)", height=400)    
    return fig


def payables_chart(df: pd.DataFrame):
    if "payables" not in df.columns or df["payables"].dropna().empty:
        return None
    # Explicit color - see note in period_investment_comparison_chart on
    # why px charts need an explicit color to export correctly as PDF images.
    fig = px.bar(df, x="day", y="payables", title="Payables (Daily)", color_discrete_sequence=["#C44E52"])
    fig.update_layout(height=350)
    return fig


def pick_date_from_data(available_days: list, label: str, default_idx: int, key_prefix: str):
    """Year -> Month -> Day dropdown picker (side by side) built only from
    dates that actually exist in the uploaded data. Avoids Streamlit's
    calendar date_input widget, which can lock up when the data spans a
    year boundary and no single month exists in both years."""
    st.sidebar.markdown(f"**{label}**")
    col_year, col_month, col_day = st.sidebar.columns(3)

    years = sorted({d.year for d in available_days})
    default_year = available_days[default_idx].year
    with col_year:
        year = st.selectbox(
            "Year", years, index=years.index(default_year), key=f"{key_prefix}_year"
        )

    months_for_year = sorted({d.month for d in available_days if d.year == year})
    month_names = {m: datetime(2000, m, 1).strftime("%b") for m in months_for_year}  # short: Jan, Feb...
    default_month = available_days[default_idx].month
    default_month = default_month if default_month in months_for_year else months_for_year[0]
    with col_month:
        month = st.selectbox(
            "Month", months_for_year, index=months_for_year.index(default_month),
            format_func=lambda m: month_names[m], key=f"{key_prefix}_month",
        )

    days_for_month = sorted({d.day for d in available_days if d.year == year and d.month == month})
    default_day = available_days[default_idx].day
    default_day = default_day if default_day in days_for_month else days_for_month[0]
    with col_day:
        day = st.selectbox(
            "Day", days_for_month, index=days_for_month.index(default_day), key=f"{key_prefix}_day"
        )

    return datetime(year, month, day).date()


def get_period_key_and_label(d, granularity: str):
    """Given a date and a granularity ('Daily', 'Monthly', 'Yearly'),
    return a (grouping_key, display_label) pair."""
    if granularity == "Daily":
        return (d.year, d.month, d.day), d.strftime("%d-%b-%y")
    elif granularity == "Yearly":
        return (d.year,), str(d.year)
    else:  # Monthly
        return (d.year, d.month), datetime(d.year, d.month, 1).strftime("%b %Y")


def build_period_summary(full_df: pd.DataFrame, selected_keys: list, granularity: str) -> pd.DataFrame:
    """Aggregate totals per selected period (day, month, or year), for
    comparing periods against each other side by side."""
    rows = []
    for key in selected_keys:
        if granularity == "Daily":
            year, month, day = key
            period_df = full_df[
                (full_df["day"].dt.year == year) & (full_df["day"].dt.month == month) & (full_df["day"].dt.day == day)
            ]
            label = datetime(year, month, day).strftime("%d-%b-%y")
        elif granularity == "Yearly":
            (year,) = key
            period_df = full_df[full_df["day"].dt.year == year]
            label = str(year)
        else:  # Monthly
            year, month = key
            period_df = full_df[(full_df["day"].dt.year == year) & (full_df["day"].dt.month == month)]
            label = datetime(year, month, 1).strftime("%b %Y")

        if period_df.empty:
            continue
        row = {"period_label": label}
        for col in ["registrations", "tickets_booked", "tickets_invested",
                    "unique_investors", "new_investors", "old_investors",
                    "investment_value", "payables"]:
            if col in period_df.columns:
                row[col] = period_df[col].sum()
        rows.append(row)
    return pd.DataFrame(rows)


def period_funnel_comparison_chart(summary_df: pd.DataFrame, granularity: str):
    """Grouped bar chart comparing Registration/Booked/Invested totals
    across selected periods."""
    fig = go.Figure()
    for col, label, color in [
        ("registrations", "Registrations", "#4C72B0"),
        ("tickets_booked", "Tickets Booked", "#55A868"),
        ("tickets_invested", "Tickets Invested", "#C44E52"),
    ]:
        if col in summary_df.columns:
            fig.add_trace(go.Bar(x=summary_df["period_label"], y=summary_df[col], name=label, marker_color=color))
    fig.update_layout(
        barmode="group", title=f"Funnel Comparison Across {granularity} Periods",
        height=420, xaxis_title=granularity[:-2] if granularity != "Daily" else "Day", yaxis_title="Count",
    )
    return fig


def period_investment_comparison_chart(summary_df: pd.DataFrame, granularity: str):
    """Bar chart comparing total Investment Value across selected periods."""
    if "investment_value" not in summary_df.columns:
        return None
    # Explicit color instead of px.bar's default colorway - Streamlit
    # registers its own 'streamlit' plotly template globally, which only
    # resolves to real colors inside a live browser session. Relying on
    # the default colorway here would silently bake in broken placeholder
    # colors (renders as solid black) whenever the chart is exported to a
    # static image outside that context, e.g. for the PDF report.
    fig = px.bar(
        summary_df, x="period_label", y="investment_value",
        title=f"Investment Value Comparison Across {granularity} Periods",
        color_discrete_sequence=["#4C72B0"],
    )
    fig.update_layout(height=420, xaxis_title=granularity[:-2] if granularity != "Daily" else "Day", yaxis_title="Investment Value (Tk)")
    return fig


def period_investor_mix_comparison_chart(summary_df: pd.DataFrame, granularity: str):
    """Stacked bar chart comparing New vs Old Unique Investors across
    selected periods."""
    if "new_investors" not in summary_df.columns or "old_investors" not in summary_df.columns:
        return None
    fig = go.Figure()
    fig.add_trace(go.Bar(x=summary_df["period_label"], y=summary_df["new_investors"], name="New Investors", marker_color="#55A868"))
    fig.add_trace(go.Bar(x=summary_df["period_label"], y=summary_df["old_investors"], name="Old Investors", marker_color="#8C8C8C"))
    fig.update_layout(
        barmode="stack", title=f"New vs Old Investors Across {granularity} Periods",
        height=420, xaxis_title=granularity[:-2] if granularity != "Daily" else "Day", yaxis_title="Unique Investors",
    )
    return fig


# --------------------------------------------------------------------------
# PDF export
# --------------------------------------------------------------------------

def generate_pdf_report(title: str, subtitle: str, kpi_dict: dict, figures: list, table_df: pd.DataFrame = None) -> bytes:
    """Builds a printable PDF: title, KPI summary table, each chart as a
    static image (via kaleido), and an optional data table at the end.
    Returns raw PDF bytes for use with st.download_button."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=0.6 * inch, bottomMargin=0.6 * inch)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(title, styles["Title"]))
    story.append(Paragraph(subtitle, styles["Normal"]))
    story.append(Paragraph(f"Generated: {datetime.now().strftime('%d %b %Y, %I:%M %p')}", styles["Normal"]))
    story.append(Spacer(1, 0.25 * inch))

    # KPI summary table
    if kpi_dict:
        kpi_rows = [["Metric", "Value"]] + [[k, v] for k, v in kpi_dict.items()]
        kpi_table = Table(kpi_rows, colWidths=[3 * inch, 2.5 * inch])
        kpi_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4C72B0")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F2F2")]),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(kpi_table)
        story.append(Spacer(1, 0.3 * inch))

    # Charts - each rendered to a static PNG via kaleido, then embedded
    page_width = A4[0] - 1.2 * inch
    for fig in figures:
        if fig is None:
            continue
        try:
            # Work on a copy with wider margins for export - funnel/donut
            # labels can sit close to the edge and get clipped at fixed
            # export width otherwise. The on-screen Streamlit chart (which
            # auto-sizes to its container) is untouched by this.
            export_fig = copy.deepcopy(fig)
            # Force a real, standalone template - Streamlit registers its
            # own 'streamlit' theme template globally on import, which only
            # resolves to real colors inside a live browser session. Static
            # image export via kaleido happens outside that context, so
            # without this the chart renders with broken placeholder colors
            # (solid black bars instead of the intended palette).
            export_fig.update_layout(template="plotly_white", margin=dict(l=180, r=60, t=60, b=60))
            png_bytes = export_fig.to_image(format="png", width=1100, height=550, scale=2)
            img = RLImage(io.BytesIO(png_bytes), width=page_width, height=page_width * (550 / 1100))
            story.append(img)
            story.append(Spacer(1, 0.25 * inch))
        except Exception as e:
            story.append(Paragraph(f"[Chart could not be rendered: {e}]", styles["Normal"]))

    # Optional data table (kept compact - only used for comparison summaries,
    # not the full raw daily table, which could be hundreds of rows)
    if table_df is not None and not table_df.empty:
        story.append(Spacer(1, 0.2 * inch))
        story.append(Paragraph("Summary Table", styles["Heading2"]))
        table_data = [list(table_df.columns)] + table_df.astype(str).values.tolist()
        data_table = Table(table_data, repeatRows=1)
        data_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4C72B0")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
        ]))
        story.append(data_table)

    doc.build(story)
    buffer.seek(0)
    return buffer.read()


def render_pdf_export_section(title: str, subtitle: str, kpi_dict: dict, figures: list, key_prefix: str, table_df: pd.DataFrame = None):
    """Two-step 'Generate PDF' -> 'Download PDF' UI. PDF is only built when
    the button is clicked (not on every rerun), since rendering charts to
    static images via kaleido has a real cost."""
    st.subheader("Printable Report")
    generate_clicked = st.button("Generate PDF", key=f"{key_prefix}_generate_pdf")

    session_key = f"{key_prefix}_pdf_bytes"
    if generate_clicked:
        with st.spinner("Generating PDF..."):
            pdf_bytes = generate_pdf_report(title, subtitle, kpi_dict, figures, table_df)
            st.session_state[session_key] = pdf_bytes

    if session_key in st.session_state:
        st.download_button(
            "Download Dashboard as PDF",
            data=st.session_state[session_key],
            file_name=f"ir_dashboard_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
            mime="application/pdf",
            key=f"{key_prefix}_download_pdf",
        )


# --------------------------------------------------------------------------
# Main app
# --------------------------------------------------------------------------

def main():
    st.title("📊 WeGro — CF Update Tracker Dashboard (IR)")
    st.caption("Internal use only.")

    uploaded_file = st.file_uploader(
        "CF Update Tracker file (.xlsx, .xls, or .csv)", type=["xlsx", "xls", "csv"]
    )

    if not uploaded_file:
        st.info("Waiting for a file to be uploaded.")
        return

    try:
        headerless_df = load_raw(uploaded_file.getvalue(), uploaded_file.name)
    except Exception as e:
        st.error(f"Could not read the uploaded file. Make sure it's a valid Excel or CSV file. Details: {e}")
        return

    if headerless_df.empty:
        st.error("The uploaded file appears to be empty.")
        return

    # Auto-detect which row holds the real column headers (handles sheets
    # with a label row like "Cumulative" above the actual headers).
    detected_row = detect_header_row(headerless_df)

    with st.expander("File preview — confirm the header row", expanded=False):
        st.caption(
            "If your sheet has extra label rows above the real column names "
            "(e.g. a 'Cumulative' row), pick the correct header row below."
        )
        preview_rows = min(10, len(headerless_df))
        st.dataframe(headerless_df.head(preview_rows), use_container_width=True)
        header_row = st.number_input(
            "Which row (0 = first row) contains the column names?",
            min_value=0, max_value=preview_rows - 1, value=detected_row, step=1,
        )

    raw_df = build_dataframe(headerless_df, header_row)
    col_map = map_columns(raw_df)

    if "day" not in col_map:
        st.error(
            "Could not find a 'Day' column in this file. "
            f"Columns found: {list(raw_df.columns)}"
        )
        return

    try:
        df = clean_data(raw_df, col_map)
    except Exception as e:
        st.error(f"Error while processing the data: {e}")
        return

    if df.empty:
        st.warning("No valid rows found after parsing dates. Please check the 'Day' column format.")
        return

    # Sidebar controls
    st.sidebar.header("Filters")
    min_day, max_day = df["day"].min().date(), df["day"].max().date()
    available_days = sorted(df["day"].dt.date.unique())
    full_df = df.copy()  # keep the unfiltered data around for month comparison mode

    filter_mode = st.sidebar.radio(
        "Select by",
        ["Date range", "Specific dates", "Compare periods"],
        help="'Date range' picks all days between a start and end. "
             "'Specific dates' lets you pick individual, non-consecutive days. "
             "'Compare periods' shows multiple days, months, or years side by side.",
    )

    if filter_mode == "Compare periods":
        granularity = st.sidebar.radio("Compare by", ["Daily", "Monthly", "Yearly"], horizontal=True, index=1)

        # Build the available period keys/labels for the chosen granularity
        period_map = {}
        for d in available_days:
            key, label = get_period_key_and_label(d, granularity)
            period_map[label] = key
        # Sort labels chronologically by their underlying key, not alphabetically
        sorted_labels = [label for label, _ in sorted(period_map.items(), key=lambda kv: kv[1])]

        default_selection = sorted_labels[-2:] if len(sorted_labels) >= 2 else sorted_labels
        selected_labels = st.sidebar.multiselect(
            f"Pick {granularity.lower()} periods to compare", options=sorted_labels, default=default_selection,
        )

        if not selected_labels:
            st.info(f"Pick at least one {granularity.lower()[:-2] if granularity != 'Daily' else 'day'} in the sidebar to compare.")
            return

        # Sort chronologically by the underlying (year, month, ...) key,
        # not by the order the user clicked them in the multiselect.
        selected_keys = sorted(period_map[label] for label in selected_labels)
        summary_df = build_period_summary(full_df, selected_keys, granularity)

        if summary_df.empty:
            st.warning("No data found for the selected periods.")
            return

        st.subheader(f"{granularity} Comparison")
        comparison_figures = []

        funnel_fig = period_funnel_comparison_chart(summary_df, granularity)
        st.plotly_chart(funnel_fig, use_container_width=True)
        comparison_figures.append(funnel_fig)

        invest_fig = period_investment_comparison_chart(summary_df, granularity)
        if invest_fig:
            st.plotly_chart(invest_fig, use_container_width=True)
            comparison_figures.append(invest_fig)

        mix_fig = period_investor_mix_comparison_chart(summary_df, granularity)
        if mix_fig:
            st.plotly_chart(mix_fig, use_container_width=True)
            comparison_figures.append(mix_fig)

        st.divider()
        st.subheader(f"{granularity} Totals")
        st.dataframe(summary_df, use_container_width=True)

        csv = summary_df.to_csv(index=False).encode("utf-8")
        st.download_button(f"Download {granularity.lower()} comparison as CSV", csv, f"ir_{granularity.lower()}_comparison.csv", "text/csv")

        st.divider()
        render_pdf_export_section(
            title="WeGro — CF Update Tracker Dashboard",
            subtitle=f"{granularity} Comparison: {', '.join(selected_labels)}",
            kpi_dict={},
            figures=comparison_figures,
            table_df=summary_df,
            key_prefix="compare",
        )
        return  # comparison mode is a distinct view - skip the day-level charts below

    if filter_mode == "Date range":
        # Streamlit's calendar date_input can lock up when data spans a
        # year boundary and no single month exists in both years (e.g. Aug
        # only exists in 2026, Oct only exists in 2025 - neither year's
        # dropdown can be reached from the other). Year -> Month -> Day
        # dropdowns built only from real data avoid that entirely.
        start = pick_date_from_data(available_days, "Start date", default_idx=0, key_prefix="start")
        end = pick_date_from_data(available_days, "End date", default_idx=-1, key_prefix="end")

        if start > end:
            st.sidebar.error("Start date is after end date - showing no data. Adjust the dates above.")
            df = df.iloc[0:0]
        else:
            df = df[(df["day"].dt.date >= start) & (df["day"].dt.date <= end)]
    else:
        selected_days = st.sidebar.multiselect(
            "Pick specific dates",
            options=available_days,
            default=[],
            format_func=lambda d: d.strftime("%d-%b-%y"),
            help="Leave empty to show all dates. Pick one or more to narrow down.",
        )
        if selected_days:
            df = df[df["day"].dt.date.isin(selected_days)]
        else:
            st.sidebar.caption(f"Showing all {len(available_days)} dates. Pick above to narrow down.")

    st.sidebar.header("Monthly Target")
    monthly_target = st.sidebar.number_input(
                "Investment value target (Tk)", min_value=0.0, value=0.0, step=100000.0,
        help="Enter the monthly investment value target manually. Used for the pacing chart.",
    )

    if df.empty:
        st.warning("No data in the selected date range.")
        return

    # KPIs
    kpi_values = kpi_row(df)
    st.divider()

    # Charts - kept in a list too, so the same figures can be reused in the PDF export
    report_figures = []

    c1, c2 = st.columns(2)
    with c1:
        funnel_fig = funnel_chart(df)
        st.plotly_chart(funnel_fig, use_container_width=True)
        report_figures.append(funnel_fig)
    with c2:
        donut_fig = investor_mix_donut(df)
        if donut_fig:
            st.plotly_chart(donut_fig, use_container_width=True)
            report_figures.append(donut_fig)
        else:
            st.info("New/Old investor columns not found in this file.")

    mix_fig = investor_mix_chart(df)
    if mix_fig:
        st.plotly_chart(mix_fig, use_container_width=True)
        report_figures.append(mix_fig)

    trend_fig = trend_chart(df)
    st.plotly_chart(trend_fig, use_container_width=True)
    report_figures.append(trend_fig)

    invest_target_fig = investment_vs_target_chart(df, monthly_target)
    st.plotly_chart(invest_target_fig, use_container_width=True)
    report_figures.append(invest_target_fig)

    pay_fig = payables_chart(df)
    if pay_fig:
        st.plotly_chart(pay_fig, use_container_width=True)
        report_figures.append(pay_fig)

    st.divider()
    st.subheader("Raw Data")
    st.dataframe(df, use_container_width=True)

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("Download filtered data as CSV", csv, "ir_daily_filtered.csv", "text/csv")

    st.divider()
    render_pdf_export_section(
        title="WeGro — CF Update Tracker Dashboard",
        subtitle=f"Period: {df['day'].min().strftime('%d %b %Y')} to {df['day'].max().strftime('%d %b %Y')}",
        kpi_dict=kpi_values,
        figures=report_figures,
        key_prefix="daterange",
    )


if __name__ == "__main__":
    main()