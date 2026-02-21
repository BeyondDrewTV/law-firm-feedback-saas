"""
Premium PDF Report Generation for Law Firm Client Feedback Analysis
Uses ReportLab to create professional, consulting-quality deliverables
"""


from io import BytesIO
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, KeepTogether
)
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.graphics.charts.barcharts import HorizontalBarChart
from reportlab.pdfgen import canvas
import re


# ===== COLOR SCHEME =====
COLORS = {
    'primary':    colors.HexColor('#1e3a8a'),   # Navy 800 — headers, key elements
    'secondary':  colors.HexColor('#0c1d4a'),   # Navy 900 — cover, darkest backgrounds
    'accent':     colors.HexColor('#d97706'),   # Gold 600 — highlights, dividers
    'accent_lt':  colors.HexColor('#fef3c7'),   # Gold 50 — light gold rows
    'navy_lt':    colors.HexColor('#eff6ff'),   # Navy 50 — light navy rows / bg
    'navy_mid':   colors.HexColor('#dbeafe'),   # Navy 100 — borders
    'background': colors.HexColor('#f8fafc'),   # Soft white background
    'success':    colors.HexColor('#15803d'),   # Green for positive
    'warning':    colors.HexColor('#d97706'),   # Gold for caution
    'text_dark':  colors.HexColor('#0f172a'),   # Near-black text
    'text_body':  colors.HexColor('#1e293b'),   # Body text
    'text_light': colors.HexColor('#64748b'),   # Muted labels
    'border':     colors.HexColor('#e2e8f0'),   # Rule lines
    'white':      colors.HexColor('#ffffff'),
}


# ===== HELPER FUNCTIONS =====


def _normalize_review_text(text: str) -> str:
    """Clean obviously contradictory phrasing from review text."""
    if not text:
        return text

    text = re.sub(
        r'never\s+\w+\s+me\s+back\s+right\s+away\s+and\s+I\s+never\s+felt\s+like\s+I\s+was\s+waiting',
        r'did not respond promptly',
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _normalize_themes(themes):
    """
    Normalize themes into a list of dicts with at least:
    {'name': str, 'mentions': int, 'percentage': float}
    """
    normalized = []

    if isinstance(themes, dict):
        # e.g. {"Communication": 5, "Responsiveness": 3}
        for name, mentions in themes.items():
            normalized.append({
                "name": str(name),
                "mentions": int(mentions),
                "percentage": 0.0,
            })
    elif isinstance(themes, list):
        for t in themes:
            if isinstance(t, dict):
                normalized.append({
                    "name": t.get("name", "Unnamed"),
                    "mentions": int(t.get("mentions", 0)),
                    "percentage": float(t.get("percentage", 0)),
                })
            else:
                normalized.append({
                    "name": str(t),
                    "mentions": 1,
                    "percentage": 0.0,
                })
    else:
        normalized = []

    return normalized


def get_custom_styles():
    """Create custom paragraph styles for the report"""
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name='CoverTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=30,
        textColor=COLORS['white'],
        alignment=TA_CENTER,
        spaceAfter=16,
        leading=36
    ))

    styles.add(ParagraphStyle(
        name='CoverSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=16,
        textColor=colors.HexColor('#dbeafe'),
        alignment=TA_CENTER,
        spaceAfter=10,
        leading=20
    ))

    styles.add(ParagraphStyle(
        name='SectionHeading',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=18,
        textColor=COLORS['primary'],
        spaceBefore=12,
        spaceAfter=14,
        leading=22,
        borderPadding=(0, 0, 6, 0)
    ))

    styles.add(ParagraphStyle(
        name='ReportReportBodyText',
        parent=styles['Normal'],
        fontName='Times-Roman',
        fontSize=11,
        textColor=COLORS['text_dark'],
        alignment=TA_JUSTIFY,
        leading=16,
        spaceAfter=12
    ))

    styles.add(ParagraphStyle(
        name='ReviewQuote',
        parent=styles['Normal'],
        fontName='Times-Italic',
        fontSize=10,
        textColor=COLORS['text_dark'],
        alignment=TA_LEFT,
        leading=14,
        leftIndent=10,
        rightIndent=10,
        spaceAfter=6
    ))

    styles.add(ParagraphStyle(
        name='Caption',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        textColor=COLORS['text_light'],
        alignment=TA_LEFT,
        leading=12
    ))

    styles.add(ParagraphStyle(
        name='PlanHeading',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=14,
        textColor=COLORS['secondary'],
        spaceBefore=10,
        spaceAfter=8,
        leading=18
    ))

    styles.add(ParagraphStyle(
        name='TableBody',
        parent=styles['Normal'],
        fontName='Times-Roman',
        fontSize=8,
        textColor=COLORS['text_dark'],
        leading=11,
        alignment=TA_LEFT,
    ))

    return styles


# ===== FOOTER AND WATERMARK HANDLERS =====


class ReportCanvas(canvas.Canvas):
    """Custom canvas for adding headers, footers, and watermarks"""

    def __init__(self, *args, **kwargs):
        self.firm_name = kwargs.pop('firm_name', '')
        self.report_date = kwargs.pop('report_date', '')
        self.is_paid_user = kwargs.pop('is_paid_user', True)
        canvas.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_page_decorations(self, num_pages):
        """Draw header bar, footer rule, and optional watermark on each page"""
        page_num = self._pageNumber
        page_width, page_height = letter

        # ── Header bar (skip cover page) ──────────────────────────
        if page_num > 1:
            self.setFillColor(COLORS['primary'])
            self.rect(0, page_height - 0.4*inch, page_width, 0.4*inch, stroke=0, fill=1)
            self.setFont('Helvetica-Bold', 8)
            self.setFillColor(COLORS['white'])
            self.drawString(0.75*inch, page_height - 0.27*inch, "LAW FIRM INSIGHTS")
            self.setFont('Helvetica', 8)
            self.setFillColor(colors.HexColor('#dbeafe'))
            firm_right = f"Confidential · {self.firm_name}"
            fw = self.stringWidth(firm_right, 'Helvetica', 8)
            self.drawString(page_width - 0.75*inch - fw, page_height - 0.27*inch, firm_right)

        # ── Gold rule above footer ─────────────────────────────────
        self.setStrokeColor(COLORS['accent'])
        self.setLineWidth(1)
        self.line(0.75*inch, 0.7*inch, page_width - 0.75*inch, 0.7*inch)

        # ── Footer text ────────────────────────────────────────────
        self.setFont('Helvetica', 7.5)
        self.setFillColor(COLORS['text_light'])
        self.drawString(0.75*inch, 0.52*inch, f"Generated {self.report_date} · lawfirminsights.app")

        page_text = f"Page {page_num} of {num_pages}"
        pw = self.stringWidth(page_text, 'Helvetica', 7.5)
        self.drawString((page_width - pw) / 2, 0.52*inch, page_text)

        self.setFillColor(colors.HexColor('#cbd5e1'))
        conf_label = "CONFIDENTIAL"
        cw = self.stringWidth(conf_label, 'Helvetica', 7.5)
        self.drawString(page_width - 0.75*inch - cw, 0.52*inch, conf_label)

        # ── Watermark for free trial (skip cover page) ─────────────
        if not self.is_paid_user and page_num > 1:
            self.saveState()
            self.setFont('Helvetica-Bold', 44)
            self.setFillColorRGB(0.85, 0.85, 0.85, alpha=0.25)
            self.translate(page_width / 2, page_height / 2)
            self.rotate(45)
            self.drawCentredString(0, 0, "FREE TRIAL REPORT")
            self.restoreState()


# ===== PAGE BUILDING FUNCTIONS =====


def _build_cover_page(story, styles, firm_name, report_date):
    """Build the executive cover page — navy full-bleed with gold accent"""
    from reportlab.platypus import HRFlowable

    # ── Navy full-page cover band ──────────────────────────────────
    cover_bg = Drawing(letter[0] - 1.5*inch, 3.4*inch)
    cover_bg.add(Rect(
        0, 0, letter[0] - 1.5*inch, 3.4*inch,
        strokeColor=None,
        fillColor=COLORS['secondary'],
        rx=6, ry=6
    ))
    # Gold accent bar at bottom of navy band
    cover_bg.add(Rect(
        0, 0, letter[0] - 1.5*inch, 5,
        strokeColor=None,
        fillColor=COLORS['accent']
    ))
    story.append(Spacer(1, 1.1*inch))
    story.append(cover_bg)
    story.append(Spacer(1, -3.4*inch))  # overlay text on band

    # Title inside the navy band
    story.append(Spacer(1, 0.65*inch))
    story.append(Paragraph("CLIENT FEEDBACK", ParagraphStyle(
        'CoverEyebrow',
        fontName='Helvetica',
        fontSize=10,
        textColor=colors.HexColor('#93c5fd'),
        alignment=TA_CENTER,
        letterSpacing=3,
        spaceAfter=6,
    )))
    story.append(Paragraph("Analysis Report", styles['CoverTitle']))
    story.append(Spacer(1, 0.2*inch))

    # Gold divider line
    hr = HRFlowable(width="70%", thickness=1.5, color=COLORS['accent'],
                    spaceBefore=0, spaceAfter=14, hAlign='CENTER')
    story.append(hr)

    story.append(Paragraph(firm_name, styles['CoverSubtitle']))
    story.append(Spacer(1, 1.5*inch))  # exit the band overlay

    # ── Below the band — meta info ─────────────────────────────────
    story.append(Spacer(1, 0.35*inch))

    meta_style = ParagraphStyle(
        'CoverMeta',
        fontName='Helvetica',
        fontSize=10,
        textColor=COLORS['text_light'],
        alignment=TA_CENTER,
        leading=16,
        spaceAfter=4,
    )
    story.append(Paragraph(f"Report Date: <b>{report_date}</b>", meta_style))
    story.append(Paragraph("Prepared by <b>Law Firm Insights</b>  ·  lawfirminsights.app", meta_style))

    # Confidentiality notice
    story.append(Spacer(1, 2.0*inch))
    notice_style = ParagraphStyle(
        'CoverNotice',
        fontName='Helvetica',
        fontSize=8.5,
        textColor=COLORS['text_light'],
        alignment=TA_CENTER,
        leading=13,
        borderPadding=8,
        backColor=COLORS['background'],
        borderColor=COLORS['border'],
        borderWidth=0.5,
        borderRadius=4,
    )
    story.append(Paragraph(
        "CONFIDENTIAL — This report contains proprietary analysis of client feedback. "
        "For internal use only. Do not distribute without authorization.",
        notice_style
    ))
    story.append(PageBreak())


def _build_executive_summary(story, styles, total_reviews, avg_rating, analysis_period, themes):
    """Build the executive summary page"""
    story.append(Paragraph("Executive Summary", styles['SectionHeading']))
    story.append(Spacer(1, 0.2*inch))

    summary = f"""
    This report analyzes <b>{total_reviews} client reviews</b> collected {analysis_period or 'over recent months'}. 
    Leveraging natural language processing and thematic analysis, we've identified the most prevalent topics 
    and trends emerging from your client feedback data.
    """
    story.append(Paragraph(summary, styles['ReportReportBodyText']))
    story.append(Spacer(1, 0.2*inch))

    # Key metrics table
    metrics_data = [
        ['Metric', 'Value'],
        ['Total Reviews Analyzed', str(total_reviews)],
        ['Average Rating', f"{avg_rating:.2f} / 5.0"],
        ['Themes Identified', str(len(themes)) if themes else '0'],
    ]

    metrics_table = Table(metrics_data, colWidths=[3*inch, 3.5*inch])
    metrics_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), COLORS['primary']),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('TOPPADDING', (0, 0), (-1, 0), 10),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, COLORS['navy_lt']]),
        ('GRID', (0, 0), (-1, -1), 0.5, COLORS['border']),
        ('TOPPADDING', (0, 1), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
    ]))

    story.append(metrics_table)
    story.append(Spacer(1, 0.3*inch))

    overview = """
    <b>Key Findings:</b><br/>
    Our analysis reveals recurring patterns in how clients discuss their experience with your firm. 
    The themes identified represent the most frequently mentioned topics across all reviews. Each theme's 
    prominence is measured by the number of times it appears in client feedback, providing a clear 
    picture of what matters most to your clients.
    """
    story.append(Paragraph(overview, styles['ReportReportBodyText']))
    story.append(PageBreak())


def _build_theme_analysis(story, styles, themes):
    """Build detailed theme breakdown"""
    story.append(Paragraph("Feedback Theme Breakdown", styles['SectionHeading']))
    story.append(Spacer(1, 0.2*inch))

    intro = """
    This section presents the key themes identified through our analysis of client feedback. 
    Each theme represents a topic or area that clients mentioned, with counts showing how frequently 
    each theme appeared across all reviews.
    """
    story.append(Paragraph(intro, styles['ReportReportBodyText']))
    story.append(Spacer(1, 0.15*inch))

    normalized = _normalize_themes(themes)
    sorted_themes = sorted(normalized, key=lambda x: x['mentions'], reverse=True)

    if not sorted_themes:
        story.append(Paragraph("No themes identified in current dataset.", styles['ReportReportBodyText']))
        story.append(PageBreak())
        return

    theme_data = [['Theme', 'Mentions', 'Percentage']]
    for theme in sorted_themes:
        theme_data.append([
            theme['name'],
            str(theme['mentions']),
            f"{theme.get('percentage', 0):.1f}%",
        ])

    theme_table = Table(theme_data, colWidths=[3.5*inch, 1.5*inch, 1.5*inch])
    theme_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), COLORS['primary']),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('ALIGN', (1, 1), (2, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('TOPPADDING', (0, 0), (-1, 0), 10),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, COLORS['navy_lt']]),
        ('GRID', (0, 0), (-1, -1), 0.5, COLORS['border']),
        ('TOPPADDING', (0, 1), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 7),
    ]))

    story.append(theme_table)
    story.append(Spacer(1, 0.4*inch))

    top_5_themes = sorted_themes[:5]
    if top_5_themes:
        drawing = Drawing(400, 200)
        chart = HorizontalBarChart()
        chart.x = 50
        chart.y = 20
        chart.height = 150
        chart.width = 330
        chart.data = [[t['mentions'] for t in top_5_themes]]
        chart.categoryAxis.categoryNames = [t['name'] for t in top_5_themes]
        chart.bars[0].fillColor = COLORS['primary']
        chart.valueAxis.valueMin = 0
        chart.categoryAxis.labels.fontSize = 9
        chart.valueAxis.labels.fontSize = 8
        drawing.add(chart)
        story.append(drawing)

    story.append(PageBreak())


def _build_positive_feedback(story, styles, positive_reviews):
    """Build positive feedback page"""
    story.append(Paragraph("What Clients Love", styles['SectionHeading']))
    story.append(Spacer(1, 0.2*inch))

    top_positive = positive_reviews[:5]

    if not top_positive:
        story.append(Paragraph("No positive reviews available in this dataset.", styles['ReportReportBodyText']))
    else:
        for review in top_positive:
            text = _normalize_review_text(review.get('review_text', ''))[:300]
            if len(review.get('review_text', '')) > 300:
                text += '...'

            review_data = [[Paragraph(f'"{text}"', styles['ReviewQuote'])]]
            review_table = Table(review_data, colWidths=[6.5*inch])
            review_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), COLORS['navy_lt']),
                ('BOX', (0, 0), (-1, -1), 1.5, COLORS['navy_mid']),
                ('TOPPADDING', (0, 0), (-1, -1), 12),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
                ('LEFTPADDING', (0, 0), (-1, -1), 12),
                ('RIGHTPADDING', (0, 0), (-1, -1), 12),
            ]))

            story.append(review_table)

            rating = review.get('rating', 5)
            date_str = review.get('date', '')
            stars = '★' * rating
            context = f"Rating: {rating}/5 {stars}"
            if date_str:
                context += f" – {date_str}"

            story.append(Paragraph(context, styles['Caption']))
            story.append(Spacer(1, 0.15*inch))

    story.append(PageBreak())


def _build_critical_feedback(story, styles, critical_reviews):
    """Build areas for improvement page"""
    story.append(Paragraph("Opportunities for Enhancement", styles['SectionHeading']))
    story.append(Spacer(1, 0.2*inch))

    top_critical = critical_reviews[:5]

    if not top_critical:
        story.append(Paragraph("No critical reviews available in this dataset.", styles['ReportReportBodyText']))
    else:
        story.append(Paragraph(
            "The following feedback examples highlight specific areas where clients experienced "
            "challenges or dissatisfaction. These insights provide valuable opportunities for "
            "process improvement and service enhancement.",
            styles['ReportReportBodyText']
        ))
        story.append(Spacer(1, 0.15*inch))

        for review in top_critical:
            text = _normalize_review_text(review.get('review_text', ''))[:300]
            if len(review.get('review_text', '')) > 300:
                text += '...'

            review_data = [[Paragraph(f'"{text}"', styles['ReviewQuote'])]]
            review_table = Table(review_data, colWidths=[6.5*inch])
            review_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), COLORS['accent_lt']),
                ('BOX', (0, 0), (-1, -1), 1.5, COLORS['accent']),
                ('TOPPADDING', (0, 0), (-1, -1), 12),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
                ('LEFTPADDING', (0, 0), (-1, -1), 12),
                ('RIGHTPADDING', (0, 0), (-1, -1), 12),
            ]))

            story.append(review_table)

            rating = review.get('rating', 1)
            date_str = review.get('date', '')
            stars = '★' * rating
            context = f"Rating: {rating}/5 {stars}"
            if date_str:
                context += f" – {date_str}"

            story.append(Paragraph(context, styles['Caption']))
            story.append(Spacer(1, 0.15*inch))

    story.append(PageBreak())


def _build_implementation_plans(story, styles, themes, subscription_type='monthly'):
    """Build implementation strategies and timelines for paid users"""
    story.append(Paragraph("Implementation Strategies & Timelines", styles['SectionHeading']))
    story.append(Spacer(1, 0.2*inch))

    intro = """
    Based on the themes identified in your client feedback, we've developed actionable implementation 
    plans with specific initiatives, timelines, and success metrics. These strategies are designed to 
    address the most impactful areas and drive measurable improvements in client satisfaction.
    """
    story.append(Paragraph(intro, styles['ReportReportBodyText']))
    story.append(Spacer(1, 0.2*inch))

    normalized = _normalize_themes(themes)
    sorted_themes = sorted(normalized, key=lambda x: x['mentions'], reverse=True)

    # Determine how many themes to include based on subscription type
    if subscription_type == 'annual':
        themes_to_plan = sorted_themes[:8]
    else:
        themes_to_plan = sorted_themes[:3]

    if not themes_to_plan:
        story.append(Paragraph("No themes available for implementation planning.", styles['ReportReportBodyText']))
        return

    for theme in themes_to_plan:
        theme_name = theme['name']
        theme_mentions = theme['mentions']
        theme_pct = theme.get('percentage', 0)

        # Theme header
        story.append(Paragraph(f"Strategic Plan: {theme_name}", styles['PlanHeading']))
        story.append(Spacer(1, 0.1*inch))

        # Theme context paragraph
        context_text = _get_theme_context(theme_name, theme_mentions, theme_pct)
        story.append(Paragraph(context_text, styles['ReportReportBodyText']))
        story.append(Spacer(1, 0.15*inch))

        # Build initiatives table
        initiatives = _get_theme_initiatives(theme_name)

        init_data = [[
            Paragraph('<b>Initiative</b>', styles['TableBody']),
            Paragraph('<b>Timeline</b>', styles['TableBody']),
            Paragraph('<b>Owner</b>', styles['TableBody']),
            Paragraph('<b>Success Metric</b>', styles['TableBody']),
        ]]

        for init in initiatives:
            init_data.append([
                Paragraph(init['initiative'], styles['TableBody']),
                Paragraph(init['timeline'], styles['TableBody']),
                Paragraph(init['owner'], styles['TableBody']),
                Paragraph(init['metric'], styles['TableBody']),
            ])

        init_table = Table(
            init_data,
            colWidths=[2.8*inch, 1.1*inch, 1.0*inch, 1.6*inch]
        )

        init_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), COLORS['primary']),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('TOPPADDING', (0, 0), (-1, 0), 10),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, COLORS['navy_lt']]),
            ('GRID', (0, 0), (-1, -1), 0.5, COLORS['border']),
            ('TOPPADDING', (0, 1), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))

        story.append(init_table)
        story.append(Spacer(1, 0.25*inch))


def _get_theme_context(theme_name, mentions, percentage):
    """Generate context paragraph for a theme"""
    theme_lower = theme_name.lower()

    if 'communication' in theme_lower:
        return f"""
        <b>Communication</b> emerged in {mentions} reviews ({percentage:.1f}% of feedback), indicating this is a 
        critical touchpoint in the client experience. Effective communication builds trust, reduces anxiety, 
        and ensures clients feel informed throughout their legal matter. The initiatives below focus on 
        establishing clear communication protocols and proactive client updates.
        """
    elif 'responsive' in theme_lower or 'response' in theme_lower:
        return f"""
        <b>Responsiveness</b> was mentioned {mentions} times ({percentage:.1f}% of feedback), highlighting client 
        expectations for timely replies and acknowledgment. In legal services, response time directly impacts 
        client confidence and satisfaction. These initiatives establish response standards and accountability 
        measures to ensure consistent follow-through.
        """
    elif 'cost' in theme_lower or 'value' in theme_lower or 'billing' in theme_lower or 'fee' in theme_lower:
        return f"""
        <b>Cost and Value</b> appeared in {mentions} reviews ({percentage:.1f}% of feedback), reflecting the importance 
        of billing transparency and perceived value. Clients want to understand what they're paying for and feel 
        their investment is justified. These strategies focus on clear fee communication and demonstrating value 
        throughout the engagement.
        """
    elif 'professional' in theme_lower or 'expertise' in theme_lower:
        return f"""
        <b>Professionalism and Expertise</b> was noted {mentions} times ({percentage:.1f}% of feedback). Clients expect 
        not only legal knowledge but also professional demeanor and presentation. These initiatives reinforce 
        standards of professional conduct and continue to build technical expertise across the firm.
        """
    elif 'outcome' in theme_lower or 'result' in theme_lower:
        return f"""
        <b>Outcomes and Results</b> emerged in {mentions} reviews ({percentage:.1f}% of feedback), underscoring that 
        clients ultimately judge their experience by the results achieved. While outcomes can't always be controlled, 
        these initiatives focus on setting realistic expectations and communicating progress throughout the matter.
        """
    else:
        return f"""
        <b>{theme_name}</b> was identified in {mentions} reviews ({percentage:.1f}% of feedback), indicating this is 
        a meaningful aspect of the client experience. The initiatives below provide a structured approach to 
        addressing this theme through targeted improvements and measurable actions.
        """


def _get_theme_initiatives(theme_name):
    """Get theme-specific initiatives with timelines, owners, and metrics"""
    theme_lower = theme_name.lower()
    
    # Communication theme initiatives
    if 'communication' in theme_lower:
        return [
            {
                'initiative': 'Establish 24-hour response SLA for all client inquiries',
                'timeline': 'Next 2 Weeks',
                'owner': 'Office Manager',
                'metric': '95% of inquiries responded to within 24 hours'
            },
            {
                'initiative': 'Implement weekly status update emails for active matters',
                'timeline': 'Week 3-4',
                'owner': 'Case Managers',
                'metric': '100% of active clients receive weekly updates'
            },
            {
                'initiative': 'Create client communication preference profiles',
                'timeline': '30 Days',
                'owner': 'Client Services',
                'metric': 'Communication preferences documented for 100% of new clients'
            },
            {
                'initiative': 'Deploy matter milestone notification system',
                'timeline': '60 Days',
                'owner': 'IT / Operations',
                'metric': 'Automated milestone alerts for all matters'
            },
            {
                'initiative': 'Quarterly communication satisfaction surveys',
                'timeline': '90 Days',
                'owner': 'Client Experience',
                'metric': '4.5+ average rating on communication questions'
            },
        ]
    
    # Responsiveness theme initiatives
    elif 'responsive' in theme_lower or 'response' in theme_lower:
        return [
            {
                'initiative': 'Implement callback triage system for urgent matters',
                'timeline': 'Next 2 Weeks',
                'owner': 'Reception / Intake',
                'metric': 'Urgent calls returned within 4 hours'
            },
            {
                'initiative': 'Establish backup coverage protocol for attorney absences',
                'timeline': 'Week 3-4',
                'owner': 'Managing Partner',
                'metric': 'Zero gaps in client coverage'
            },
            {
                'initiative': 'Deploy response time tracking dashboard',
                'timeline': '30 Days',
                'owner': 'Operations',
                'metric': 'Real-time visibility into response metrics'
            },
            {
                'initiative': 'Create email templates for common client questions',
                'timeline': '45 Days',
                'owner': 'Attorneys',
                'metric': '30% reduction in response preparation time'
            },
            {
                'initiative': 'Monthly response time performance reviews',
                'timeline': '90 Days',
                'owner': 'Partners',
                'metric': 'Average response time under 12 hours'
            },
        ]
    
    # Cost/Value/Billing theme initiatives
    elif 'cost' in theme_lower or 'value' in theme_lower or 'billing' in theme_lower or 'fee' in theme_lower:
        return [
            {
                'initiative': 'Develop fee range estimates for common matters',
                'timeline': 'Next 2 Weeks',
                'owner': 'Finance / Partners',
                'metric': 'Fee estimates provided at initial consultation for all standard matters'
            },
            {
                'initiative': 'Create billing transparency summaries with plain English',
                'timeline': 'Week 3-4',
                'owner': 'Billing Manager',
                'metric': 'Narrative billing summaries for 100% of invoices'
            },
            {
                'initiative': 'Implement value-add touchpoints (educational content)',
                'timeline': '30 Days',
                'owner': 'Marketing',
                'metric': 'Monthly legal insights newsletter sent to all active clients'
            },
            {
                'initiative': 'Offer payment plan options for qualifying matters',
                'timeline': '60 Days',
                'owner': 'Finance',
                'metric': 'Payment plans available and clearly communicated'
            },
            {
                'initiative': 'Conduct value perception surveys at matter conclusion',
                'timeline': '90 Days',
                'owner': 'Client Experience',
                'metric': '4.0+ average rating on value-for-money questions'
            },
        ]
    
    # Professionalism/Expertise theme initiatives
    elif 'professional' in theme_lower or 'expertise' in theme_lower:
        return [
            {
                'initiative': 'Establish firm-wide professional standards guide',
                'timeline': 'Next 2 Weeks',
                'owner': 'Managing Partner',
                'metric': 'Standards distributed and acknowledged by all staff'
            },
            {
                'initiative': 'Implement quarterly CLE and training sessions',
                'timeline': 'Week 3-4',
                'owner': 'HR / Training',
                'metric': '100% attorney participation in quarterly CLE'
            },
            {
                'initiative': 'Create mentorship program for associate development',
                'timeline': '30 Days',
                'owner': 'Senior Partners',
                'metric': 'All associates paired with mentors'
            },
            {
                'initiative': 'Conduct peer review of client-facing communications',
                'timeline': '60 Days',
                'owner': 'Practice Leaders',
                'metric': 'Monthly peer review sessions held'
            },
            {
                'initiative': 'Annual professionalism and expertise client surveys',
                'timeline': '90 Days',
                'owner': 'Client Experience',
                'metric': '4.7+ average rating on professionalism metrics'
            },
        ]
    
    # Outcome/Results theme initiatives
    elif 'outcome' in theme_lower or 'result' in theme_lower:
        return [
            {
                'initiative': 'Create 1-page "What to Expect" handouts for your 3 most common case types and review with partners',
                'timeline': 'Next 2 Weeks',
                'owner': 'Attorneys',
                'metric': 'Handouts used in 90% of new matter intakes'
            },
            {
                'initiative': 'Add outcome ranges (best / likely / conservative) to your standard intake conversation script',
                'timeline': 'Week 3-4',
                'owner': 'Attorneys',
                'metric': 'Outcome ranges documented in intake notes for 100% of new matters'
            },
            {
                'initiative': 'Introduce a "mid-matter expectations check-in" call template and schedule for longer cases',
                'timeline': '30 Days',
                'owner': 'Case Managers',
                'metric': 'Check-in completed for all matters lasting over 90 days'
            },
            {
                'initiative': 'Build a simple outcome summary template for closed matters (result, key drivers, lessons)',
                'timeline': '60 Days',
                'owner': 'Attorneys',
                'metric': 'Outcome summaries completed for 80%+ of closed matters'
            },
            {
                'initiative': 'Launch a short post-matter survey focused on expectations vs actual outcome',
                'timeline': '90 Days',
                'owner': 'Client Experience',
                'metric': 'At least 40% survey response rate and baseline satisfaction score collected'
            },
        ]
    
    # Generic template for other themes
    else:
        return [
            {
                'initiative': f'Conduct focused assessment of {theme_name} feedback',
                'timeline': 'Next 2 Weeks',
                'owner': 'Practice Leader',
                'metric': 'Assessment report completed with specific findings'
            },
            {
                'initiative': f'Develop targeted improvement plan for {theme_name}',
                'timeline': 'Week 3-4',
                'owner': 'Operations',
                'metric': 'Detailed improvement plan documented and approved'
            },
            {
                'initiative': f'Implement quick-win improvements for {theme_name}',
                'timeline': '30 Days',
                'owner': 'Team Leads',
                'metric': 'At least 3 quick-win initiatives completed'
            },
            {
                'initiative': f'Roll out comprehensive {theme_name} enhancement program',
                'timeline': '60 Days',
                'owner': 'Department Head',
                'metric': 'Program launched and communicated to all staff'
            },
            {
                'initiative': f'Measure and report {theme_name} satisfaction improvement',
                'timeline': '90 Days',
                'owner': 'Client Experience',
                'metric': '10%+ improvement in theme-related feedback scores'
            },
        ]


def _build_upgrade_cta(story, styles):
    """Build upgrade call-to-action for free trial users"""
    story.append(Spacer(1, 0.5*inch))

    cta_content = """
    <b>Unlock Your Complete Action Plan</b><br/><br/>

    This Free Trial Report provides valuable insights into your client feedback themes. 
    To access the full value of this analysis, upgrade to a paid plan to receive:<br/><br/>

    • Detailed 90-day implementation roadmaps for your top improvement areas<br/>
    • Week-by-week action plans with specific tasks and responsible parties<br/>
    • Measurable KPIs and success metrics for each initiative<br/>
    • Quick wins, 30-day goals, and 90-day transformation strategies<br/>
    • Unlimited reports and ongoing analysis<br/><br/>

    <b>Upgrade now to turn insights into results.</b><br/>
    Visit your account dashboard to explore pricing options.
    """

    cta_data = [[Paragraph(cta_content, styles['ReportReportBodyText'])]]
    cta_table = Table(cta_data, colWidths=[6.5*inch])
    cta_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#e6f3ff')),
        ('BOX', (0, 0), (-1, -1), 2, COLORS['accent']),
        ('TOPPADDING', (0, 0), (-1, -1), 20),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 20),
        ('LEFTPADDING', (0, 0), (-1, -1), 20),
        ('RIGHTPADDING', (0, 0), (-1, -1), 20),
    ]))

    story.append(cta_table)


# ===== MAIN FUNCTION =====


def generate_pdf_report(
    firm_name,
    total_reviews,
    avg_rating,
    themes,
    top_praise,
    top_complaints,
    is_paid_user=False,
    subscription_type='monthly',
    analysis_period=None
):
    """
    Generate a premium PDF report for law firm client feedback analysis.
    
    Args:
        firm_name: Name of the law firm
        total_reviews: Total number of reviews analyzed
        avg_rating: Average rating across all reviews
        themes: List of theme dicts with name, mentions, percentage
        top_praise: List of top positive reviews
        top_complaints: List of critical reviews
        is_paid_user: Boolean - whether user has paid access (one-time or subscription)
        subscription_type: String - 'trial', 'onetime', 'monthly', or 'annual'
        analysis_period: String describing the time period analyzed
    """
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
    )

    styles = get_custom_styles()
    story = []

    report_date = datetime.now().strftime("%B %d, %Y")

    # PAGE 1: Cover
    _build_cover_page(story, styles, firm_name, report_date)

    # PAGE 2: Executive Summary
    _build_executive_summary(story, styles, total_reviews, avg_rating, analysis_period, themes)

    # PAGE 3: Theme Analysis
    _build_theme_analysis(story, styles, themes)

    # PAGE 4: Positive Feedback
    _build_positive_feedback(story, styles, top_praise)

    # PAGE 5: Critical Feedback
    _build_critical_feedback(story, styles, top_complaints)

    # PAID USERS: Implementation Plans
    # FREE TRIAL: Upgrade CTA
    if is_paid_user:
        _build_implementation_plans(story, styles, themes, subscription_type)
    else:
        _build_upgrade_cta(story, styles)

    # Build PDF with custom canvas
    doc.build(
        story,
        canvasmaker=lambda *args, **kwargs: ReportCanvas(
            *args,
            firm_name=firm_name,
            report_date=report_date,
            is_paid_user=is_paid_user,
            **kwargs
        )
    )

    buffer.seek(0)
    return buffer
