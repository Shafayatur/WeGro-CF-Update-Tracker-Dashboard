"""
WeGro — Shared PDF export helpers
---------------------------------
Extracted from the original app.py so both dashboard tabs (Daily Funnel
Tracker and Investor Segmentation) generate PDFs the same way: same layout,
same KPI-table styling, same chart-export workaround for kaleido/Streamlit
theming. Nothing here is tab-specific — pass in whatever title, KPIs,
Plotly figures, and optional summary table you want in the PDF.
"""

import io
import copy
from datetime import datetime

import pandas as pd
import streamlit as st
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, Table, TableStyle,
)


def generate_pdf_report(title: str, subtitle: str, kpi_dict: dict, figures: list,
                         table_df: pd.DataFrame = None, table_heading: str = "Summary Table",
                         landscape_table: bool = False) -> bytes:
    """Builds a printable PDF: title, KPI summary table, each chart as a
    static image (via kaleido), and an optional data table at the end.
    Returns raw PDF bytes for use with st.download_button.

    landscape_table: use a landscape page instead of portrait. Worth
    turning on for reports whose table has several text-heavy columns
    (names, project names, categories) - landscape roughly doubles the
    usable width, so wrapped text needs far fewer lines and there's a lot
    more margin for error versus a tight portrait column."""
    buffer = io.BytesIO()
    pagesize = landscape(A4) if landscape_table else A4
    doc = SimpleDocTemplate(buffer, pagesize=pagesize, topMargin=0.6 * inch, bottomMargin=0.6 * inch)
    styles = getSampleStyleSheet()
    centered = styles["Normal"].clone("centered")
    centered.alignment = TA_CENTER
    story = []

    story.append(Paragraph(title, styles["Title"]))
    story.append(Paragraph(subtitle, centered))
    story.append(Paragraph(f"Generated: {datetime.now().strftime('%d %b %Y, %I:%M %p')}", centered))
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
    page_width = pagesize[0] - 1.2 * inch
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

    # Optional data table (kept compact - callers should pass a trimmed
    # summary, not a full raw table that could run hundreds of rows)
    if table_df is not None and not table_df.empty:
        story.append(Spacer(1, 0.2 * inch))
        story.append(Paragraph(table_heading, styles["Heading2"]))

        cell_style = styles["Normal"].clone("cell")
        cell_style.fontSize = 7
        cell_style.leading = 9
        header_style = styles["Normal"].clone("header")
        header_style.fontSize = 7
        header_style.leading = 9
        header_style.textColor = colors.white
        header_style.fontName = "Helvetica-Bold"

        # Wrap every cell in a Paragraph so long text (names, project names)
        # wraps onto multiple lines within its column instead of forcing
        # the column wider than the page and getting cropped at the edge.
        header_row = [Paragraph(str(c), header_style) for c in table_df.columns]
        body_rows = [
            [Paragraph(str(v), cell_style) for v in row]
            for row in table_df.astype(str).values.tolist()
        ]
        table_data = [header_row] + body_rows

        # Explicit column widths that always sum to the available page
        # width, so the table can never overflow the margin - long
        # columns (names, project names) get proportionally more room.
        num_cols = len(table_df.columns)
        col_weights = []
        for col in table_df.columns:
            name = str(col).lower()
            if "name" in name or "project" in name or "category" in name:
                col_weights.append(2.2)
            elif "invested" in name or "amount" in name:
                col_weights.append(1.3)
            else:
                col_weights.append(1.0)
        total_weight = sum(col_weights)
        col_widths = [page_width * (w / total_weight) for w in col_weights]

        data_table = Table(table_data, colWidths=col_widths, repeatRows=1)
        data_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4C72B0")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(data_table)

    doc.build(story)
    buffer.seek(0)
    return buffer.read()


def render_pdf_export_section(title: str, subtitle: str, kpi_dict: dict, figures: list, key_prefix: str,
                               table_df: pd.DataFrame = None, table_heading: str = "Summary Table",
                               file_prefix: str = "ir_dashboard", landscape_table: bool = False):
    """Two-step 'Generate PDF' -> 'Download PDF' UI. PDF is only built when
    the button is clicked (not on every rerun), since rendering charts to
    static images via kaleido has a real cost."""
    st.subheader("Printable Report")
    generate_clicked = st.button("Generate PDF", key=f"{key_prefix}_generate_pdf")

    session_key = f"{key_prefix}_pdf_bytes"
    if generate_clicked:
        with st.spinner("Generating PDF..."):
            pdf_bytes = generate_pdf_report(title, subtitle, kpi_dict, figures, table_df, table_heading, landscape_table)
            st.session_state[session_key] = pdf_bytes

    if session_key in st.session_state:
        st.download_button(
            "Download Dashboard as PDF",
            data=st.session_state[session_key],
            file_name=f"{file_prefix}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
            mime="application/pdf",
            key=f"{key_prefix}_download_pdf",
        )