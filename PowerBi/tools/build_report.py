"""DataSentinel Power BI report pages (PBIR): sidebar navigation, KPI cards with status pills and
sparklines, chart cards, and the hidden Customer profile drill-through page.

Usage:  python PowerBi/tools/build_report.py [path/to/PowerBi/model]
Run it with Power BI Desktop closed, after build_model.py. It rewrites every page folder.
Canvas 1920 x 1080 (reference image 1600 x 900 scaled 1.2).
"""
import json
import os
import shutil
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "model")
REPORT = os.path.join(ROOT, "DataSentinel.Report")
DEF = os.path.join(REPORT, "definition")
PAGES = os.path.join(DEF, "pages")
M = "_Measures"

# Reference image palette
BLUE, GREEN, PURPLE, ORANGE, RED, AMBER = "#2F6FDB", "#1FAE7A", "#6B5BD6", "#F06A35", "#D9363E", "#F2B33D"
GREY, TRACK = "#9CA3AF", "#EDF0F4"
TEXT, SUB, BORDER, BG, WHITE = "#111827", "#6B7280", "#E3E8EF", "#EEF2F7", "#FFFFFF"
NAV_BG, NAV_ACTIVE_BG, NAV_TEXT, NAV_ICON = "#0B1B3D", "#1E4FD8", "#C3CCDA", "#8C99B0"
PILLS = {  # background, text
    "blue": ("#E8F0FD", "#1D4ED8"), "green": ("#E3F6EE", "#0F7A53"), "amber": ("#FDF1D6", "#92600A"),
    "red": ("#FDE2E2", "#B42318"), "yellow": ("#FCEFC7", "#7A5A00"), "grey": ("#F1F3F6", "#4B5563"),
}

VIS_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.7.0/schema.json"
PAGE_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json"

SIDEBAR_W = 264
X0, X1 = 298, 1886
W = X1 - X0
GAP = 20
KPI_Y, KPI_H = 120, 118
R2_Y, R2_H = 258, 326
R3_Y, R3_H = 604, 420

NAV = [("overview", "Overview", "⌂"), ("data-quality", "Data Quality", "◇"),
       ("revenue-assurance", "Revenue Assurance", "€"), ("incidents", "Incidents", "△"),
       ("customer-360", "Customer 360", "○"), ("network-app", "Network & App", "≋")]


# ---------- expression helpers ----------
def lit(v):
    return {"expr": {"Literal": {"Value": v}}}


def s(text):
    return "'" + text.replace("'", "''") + "'"


def color(c):
    return {"solid": {"color": lit(s(c))}}


def col(table, name):
    return {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}}


def meas(name):
    return {"Measure": {"Expression": {"SourceRef": {"Entity": M}}, "Property": name}}


def agg(table, name, fn=0):
    return {"Aggregation": {"Function": fn, "Expression": col(table, name)}}


AGG_NAMES = {0: "Sum", 1: "Average", 3: "Min", 4: "Max"}


def ref(field):
    if "Measure" in field:
        return f"{M}.{field['Measure']['Property']}"
    if "Column" in field:
        return f"{field['Column']['Expression']['SourceRef']['Entity']}.{field['Column']['Property']}"
    a = field["Aggregation"]
    c = a["Expression"]["Column"]
    return f"{AGG_NAMES[a['Function']]}({c['Expression']['SourceRef']['Entity']}.{c['Property']})"


def proj(field, display=None):
    if "Measure" in field:
        p = {"field": field, "queryRef": ref(field), "nativeQueryRef": field["Measure"]["Property"]}
    elif "Column" in field:
        p = {"field": field, "queryRef": ref(field), "nativeQueryRef": field["Column"]["Property"], "active": True}
    else:
        a = field["Aggregation"]
        p = {"field": field, "queryRef": ref(field),
             "nativeQueryRef": f"{AGG_NAMES[a['Function']]} of {a['Expression']['Column']['Property']}"}
    if display:
        p["displayName"] = display
    return p


def sourced(field, alias):
    out = json.loads(json.dumps(field))

    def walk(o):
        if isinstance(o, dict):
            if "SourceRef" in o and "Entity" in o["SourceRef"]:
                o["SourceRef"] = {"Source": alias}
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(out)
    return out


# ---------- filters ----------
def filter_not_in(table, column, values):
    f = col(table, column)
    return {"name": f"f_{column}_not_in", "field": f, "type": "Categorical", "filter": {
        "Version": 2, "From": [{"Name": "t", "Entity": table, "Type": 0}],
        "Where": [{"Condition": {"Not": {"Expression": {"In": {
            "Expressions": [sourced(f, "t")], "Values": [[{"Literal": {"Value": s(v)}}] for v in values]}}}}}]}}


def filter_top_n(table, column, n, by_measure):
    f = col(table, column)
    return {"name": f"f_top_{column}", "field": f, "type": "TopN", "filter": {
        "Version": 2,
        "From": [
            {"Name": "subquery", "Expression": {"Subquery": {"Query": {
                "Version": 2,
                "From": [{"Name": "t", "Entity": table, "Type": 0}, {"Name": "m", "Entity": M, "Type": 0}],
                "Select": [{**sourced(f, "t"), "Name": "field"}],
                "OrderBy": [{"Direction": 2, "Expression": sourced(meas(by_measure), "m")}],
                "Top": n}}}, "Type": 2},
            {"Name": "t", "Entity": table, "Type": 0}],
        "Where": [{"Condition": {"In": {"Expressions": [sourced(f, "t")],
                                        "Table": {"SourceRef": {"Source": "subquery"}}}}}]}}


# ---------- formatting ----------
ALL_POINTS = {"data": [{"dataViewWildcard": {"matchingOption": 1}}]}
OFF = lambda: [{"properties": {"show": lit("false")}}]


def series_color(field, c):
    return {"properties": {"fill": color(c)}, "selector": {"metadata": ref(field)}}


def series_color_by_measure(field, color_measure):
    return {"properties": {"fill": {"solid": {"color": {"expr": meas(color_measure)}}}},
            "selector": {**ALL_POINTS, "metadata": ref(field)}}


def value_color(table, column, value, c):
    return {"properties": {"fill": color(c)}, "selector": {"data": [{"scopeId": {"Comparison": {
        "ComparisonKind": 0, "Left": col(table, column), "Right": {"Literal": {"Value": s(value)}}}}}]}}


def cell_rule(bg_measure, font_measure, target):
    return [{"properties": {"backColor": {"solid": {"color": {"expr": meas(bg_measure)}}},
                            "fontColor": {"solid": {"color": {"expr": meas(font_measure)}}}},
             "selector": {**ALL_POINTS, "metadata": ref(target)}}]


def shadow():
    return [{"properties": {"show": lit("true"), "color": color("#0B1B3D"), "transparency": lit("90D"),
                            "position": lit("'Outer'"), "preset": lit("'Custom'"), "shadowBlur": lit("14D"),
                            "shadowDistance": lit("3D"), "shadowSpread": lit("0D"), "angle": lit("90D")}}]


def frame(title=None, subtitle=None, bg=WHITE, border=True, radius="12D", border_color=BORDER, pad=True):
    o = {"background": [{"properties": {"show": lit("true" if bg else "false"),
                                        **({"color": color(bg), "transparency": lit("0D")} if bg else {})}}],
         "border": [{"properties": {"show": lit("true" if border else "false"), "color": color(border_color),
                                    "radius": lit(radius), "width": lit("1D")}}],
         "dropShadow": shadow() if (bg and border) else OFF(),
         "visualHeader": OFF()}
    if title:
        o["title"] = [{"properties": {"show": lit("true"), "text": lit(s(title)), "alignment": lit("'left'"),
                                      "fontColor": color(TEXT), "fontSize": lit("14D"), "bold": lit("true"),
                                      "fontFamily": lit("'Arial'")}}]
    else:
        o["title"] = OFF()
    if subtitle:
        o["subTitle"] = [{"properties": {"show": lit("true"), "text": lit(s(subtitle)), "fontColor": color(SUB),
                                         "fontSize": lit("10D"), "fontFamily": lit("'Arial'")}}]
    if pad:
        o["padding"] = [{"properties": {"top": lit("10D"), "bottom": lit("8D"), "left": lit("14D"),
                                        "right": lit("14D")}}]
    else:
        o["padding"] = [{"properties": {"top": lit("0D"), "bottom": lit("0D"), "left": lit("0D"),
                                        "right": lit("0D")}}]
    return o


# ---------- visual builders ----------
VISUALS = []


CODE = {"revenue-assurance": "ra", "customer-profile": "cp", "customer-360": "cu", "data-quality": "dq",
        "network-app": "nw", "incidents": "in", "overview": "ov"}


def put(page, name, pos, visual, filters=None):
    for k, v in CODE.items():
        name = name.replace(k, v)
    x, y, w, h = (round(v) for v in pos)
    z = len(VISUALS)
    doc = {"$schema": VIS_SCHEMA, "name": name,
           "position": {"x": x, "y": y, "z": z, "width": w, "height": h, "tabOrder": z},
           "visual": visual}
    if filters:
        doc["filterConfig"] = {"filters": filters}
    VISUALS.append((page, name, doc))


def query(buckets, sort=None, displays=None):
    displays = displays or {}
    q = {"queryState": {k: {"projections": [proj(f, displays.get(ref(f))) for f in v]} for k, v in buckets.items()}}
    if sort:
        q["sortDefinition"] = {"sort": [{"field": sort[0], "direction": sort[1]}], "isDefaultSort": True}
    return q


def chart(page, name, vtype, pos, buckets, title, subtitle=None, objects=None, sort=None, filters=None,
          displays=None, meta=None):
    put(page, name, pos, {"visualType": vtype, "query": query(buckets, sort, displays),
                          "visualContainerObjects": frame(title, subtitle),
                          "objects": objects or {}, "drillFilterOtherVisuals": True}, filters)
    if meta:
        x, y, w, h = pos
        chip = (x + w - 156, y + 12, 140, 30)
        shape(page, f"{name}-meta-bg", chip, WHITE, radius="8D", border="#D9DEE7")
        if meta.startswith("="):  # measure-driven text
            text_card(page, f"{name}-meta", (chip[0] + 4, chip[1] + 2, chip[2] - 8, 26), meta[1:], "#374151", 9)
        else:
            textbox(page, f"{name}-meta", (chip[0], chip[1] + 6, chip[2], 22),
                    [(meta, {"fontSize": "9pt", "color": "#374151"})], align="center")


def shape(page, name, pos, fill, radius="12D", border=None, nav=None, lifted=False):
    vco = {"background": [{"properties": {"show": lit("true"), "color": color(fill), "transparency": lit("0D")}}],
           "border": [{"properties": {"show": lit("true" if border else "false"),
                                      **({"color": color(border), "width": lit("1D")} if border else {}),
                                      "radius": lit(radius)}}],
           "dropShadow": shadow() if lifted else OFF(), "title": OFF(), "visualHeader": OFF()}
    if nav:
        vco["visualLink"] = [{"properties": {"show": lit("true"), "type": lit("'PageNavigation'"),
                                             "navigationSection": lit(s(nav))}}]
    put(page, name, pos, {"visualType": "shape",
                          "objects": {"shape": [{"properties": {"tileShape": lit("'rectangle'")}}],
                                      "fill": [{"properties": {"show": lit("false")}}],
                                      "outline": OFF()},
                          "visualContainerObjects": vco})


def textbox(page, name, pos, runs, align="left", paragraphs=None):
    paras = paragraphs or [runs]
    put(page, name, pos, {
        "visualType": "textbox",
        "objects": {"general": [{"properties": {"paragraphs": [
            {"textRuns": [{"value": t, "textStyle": {"fontFamily": "Arial", **st}} for t, st in p],
             "horizontalTextAlignment": align}
            for p in paras]}}]},
        "visualContainerObjects": {"background": OFF(), "border": OFF(), "dropShadow": OFF(),
                                   "visualHeader": OFF(),
                                   "padding": [{"properties": {"top": lit("0D"), "bottom": lit("0D"),
                                                               "left": lit("0D"), "right": lit("0D")}}]}})


def text_card(page, name, pos, measure, fg, size, bg=None, bold=False, align="left", radius="14D", nav=None,
              dynamic=False):
    """A classic card used to show a text measure (pill, meta label). dynamic: colours from <measure> Bg/Fg."""
    vco = frame(bg=bg, border=False, radius=radius, pad=False)
    vco["border"] = [{"properties": {"show": lit("true" if bg else "false"),
                                     "color": color(bg or WHITE), "radius": lit(radius)}}]
    if dynamic:
        dyn = lambda suffix: {"solid": {"color": {"expr": meas(f"{measure} {suffix}")}}}
        vco["background"] = [{"properties": {"show": lit("true"), "color": dyn("Bg"), "transparency": lit("0D")}}]
        vco["border"] = [{"properties": {"show": lit("true"), "color": dyn("Bg"), "radius": lit(radius)}}]
    if nav:
        vco["visualLink"] = [{"properties": {"show": lit("true"), "type": lit("'PageNavigation'"),
                                             "navigationSection": lit(s(nav))}}]
    put(page, name, pos, {
        "visualType": "card",
        "query": query({"Values": [meas(measure)]}),
        "visualContainerObjects": vco,
        "objects": {"categoryLabels": OFF(),
                    "labels": [{"properties": {"color": ({"solid": {"color": {"expr": meas(f"{measure} Fg")}}}
                                                         if dynamic else color(fg)), "fontSize": lit(f"{size}D"),
                                               "bold": lit("true" if bold else "false"),
                                               "fontFamily": lit("'Arial'")}}]},
        "drillFilterOtherVisuals": True})


def kpi(page, name, pos, label, dot, measure, pill_measure=None, pill="blue", spark=None, nav=None,
        units="0D", decimals=None):
    """White KPI card: dot + label, big left-aligned number, status pill, optional sparkline on the right."""
    x, y, w, h = pos
    shape(page, f"{name}-bg", pos, WHITE, border=BORDER, nav=nav, lifted=True)
    textbox(page, f"{name}-label", (x + 18, y + 14, w - 36, 22),
            [("● ", {"fontSize": "10pt", "color": dot}),
             (label, {"fontSize": "11pt", "color": "#374151", "fontWeight": "bold"})])
    region = w * 0.58 if spark else w - 24
    vco = frame(bg=None, border=False, pad=False)
    if nav:
        vco["visualLink"] = [{"properties": {"show": lit("true"), "type": lit("'PageNavigation'"),
                                             "navigationSection": lit(s(nav))}}]
    put(page, f"{name}-value", (x + 10, y + 36, region, 50), {
        "visualType": "multiRowCard", "query": query({"Values": [meas(measure)]}),
        "visualContainerObjects": vco,
        "objects": {"categoryLabels": OFF(),
                    "dataLabels": [{"properties": {"color": color(TEXT), "fontSize": lit("24D"),
                                                   "fontFamily": lit("'Arial Black'")}}],
                    "card": [{"properties": {"barShow": lit("false"), "outlineStyle": lit("0D")}}]},
        "drillFilterOtherVisuals": True})
    if pill_measure:
        bg, fg = PILLS["grey" if pill == "status" else pill]
        text_card(page, f"{name}-pill", (x + 18, y + 88, min(region - 24, 250), 24), pill_measure, fg, 9,
                  bg=bg, bold=True, nav=nav, dynamic=pill == "status")
    if spark:
        fx, fy, c = spark
        put(page, f"{name}-spark", (x + region + 4, y + 34, w - region - 18, 72), {
            "visualType": "lineChart", "query": query({"Category": [fx], "Y": [fy]}),
            "visualContainerObjects": frame(bg=None, border=False, pad=False),
            "objects": {"categoryAxis": OFF(), "valueAxis": OFF(), "legend": OFF(),
                        "dataPoint": [series_color(fy, c)],
                        "lineStyles": [{"properties": {"strokeWidth": lit("2D"), "showMarker": lit("false")}}]},
            "drillFilterOtherVisuals": False})


def pill_slicer(page, name, pos, label, table, column, mode="Dropdown"):
    x, y, w, h = pos
    shape(page, f"{name}-bg", pos, WHITE, radius="22D", border="#DADDE3")
    textbox(page, f"{name}-label", (x + 16, y + 12, 110, 22), [(label, {"fontSize": "10pt", "color": "#4B5563"})])
    lw = 8 * len(label) + 22
    objects = {"data": [{"properties": {"mode": lit(s(mode))}}], "header": OFF(),
               "items": [{"properties": {"fontColor": color(TEXT), "bold": lit("true"), "fontSize": lit("10D"),
                                         "fontFamily": lit("'Arial'"),
                                         "outline": lit("'None'")}}]}
    if mode == "Between":
        objects["slider"] = OFF()
    put(page, name, (x + lw, y + 2, w - lw - 12, h - 4), {
        "visualType": "slicer", "query": query({"Values": [col(table, column)]}),
        "visualContainerObjects": frame(bg=None, border=False, pad=False),
        "objects": objects, "drillFilterOtherVisuals": True})


def sample_pill(page, pos):
    x, y, w, h = pos
    shape(page, f"{page}-sample-bg", pos, "#2F5BB7", radius="22D", lifted=True)
    textbox(page, f"{page}-sample", (x, y + 11, w, 24),
            [("Sample data", {"fontSize": "10pt", "fontWeight": "bold", "color": WHITE})], align="center")


def nav_button(page, target, label, icon, y, active):
    x, w, h = 16, SIDEBAR_W - 32, 44
    if active:
        shape(page, f"{page}-nav-{target}-bg", (x, y, w, h), NAV_ACTIVE_BG, radius="8D")
    textbox(page, f"{page}-nav-{target}-txt", (x + 16, y + 11, w - 24, 24),
            [(f"{icon}   ", {"fontSize": "11pt", "color": WHITE if active else NAV_ICON}),
             (label, {"fontSize": "11pt", "color": WHITE if active else NAV_TEXT, "fontWeight": "bold"})])
    put(page, f"{page}-nav-{target}", (x, y, w, h), {
        "visualType": "shape",
        "objects": {"shape": [{"properties": {"tileShape": lit("'rectangle'")}}],
                    "fill": [{"properties": {"show": lit("false")}}],
                    "outline": OFF()},
        "visualContainerObjects": {
            "visualLink": [{"properties": {"show": lit("true"), "type": lit("'PageNavigation'"),
                                           "navigationSection": lit(s(target))}}],
            "background": OFF(), "border": OFF(), "dropShadow": OFF(), "title": OFF(), "visualHeader": OFF()}})


def chrome(page, title, subtitle, number=None, pills=()):
    """Sidebar, title block, filter pills, sample-data pill, footer."""
    shape(page, f"{page}-sidebar", (0, 0, SIDEBAR_W, 1080), NAV_BG, radius="0D")
    shape(page, f"{page}-logo-bg", (26, 28, 40, 40), BLUE, radius="10D")
    textbox(page, f"{page}-logo-icon", (26, 33, 40, 30), [("◈", {"fontSize": "15pt", "color": WHITE})],
            align="center")
    textbox(page, f"{page}-logo-text", (76, 33, 180, 32),
            [("DataSentinel", {"fontSize": "15pt", "fontWeight": "bold", "color": WHITE})])
    textbox(page, f"{page}-nav-label", (30, 106, 200, 20),
            [("REPORT", {"fontSize": "9pt", "fontWeight": "bold", "color": "#7C8BA8"})])
    for i, (target, label, icon) in enumerate(NAV):
        y = 136 + i * 48
        active = target == page
        nav_button(page, target, label, icon, y, active)
    shape(page, f"{page}-gold-bg", (18, 962, SIDEBAR_W - 36, 92), "#E9EEF7", radius="10D")
    textbox(page, f"{page}-gold-text", (34, 976, SIDEBAR_W - 66, 70), [], paragraphs=[
        [("Gold layer", {"fontSize": "10pt", "fontWeight": "bold", "color": TEXT})],
        [("12 mart tables · refresh after each pipeline run", {"fontSize": "9pt", "color": SUB})]])

    textbox(page, f"{page}-title", (X0, 32, 900, 40), [(title, {"fontSize": "21pt", "fontWeight": "bold",
                                                                "color": TEXT})])
    textbox(page, f"{page}-subtitle", (X0, 80, 900, 24), [(subtitle, {"fontSize": "11pt", "color": "#4B5563"})])
    x = X1 - 116
    sample_pill(page, (x, 62, 116, 44))
    for label, table, column, width, mode in reversed(pills):
        x -= width + 10
        pill_slicer(page, f"{page}-pill-{column}", (x, 62, width, 44), label, table, column, mode)
    textbox(page, f"{page}-footer", (X0, 1046, 900, 22),
            [("DataSentinel · design preview with sample values, real values come from the Gold marts",
              {"fontSize": "8pt", "color": GREY})])
    if number:
        textbox(page, f"{page}-pageno", (X1 - 200, 1046, 200, 22),
                [(f"Page {number} of 6", {"fontSize": "8pt", "color": GREY})], align="right")


def cols(n, y, h, x0=X0, width=W, weights=None):
    weights = weights or [1] * n
    unit = (width - GAP * (n - 1)) / sum(weights)
    out, x = [], x0
    for wgt in weights:
        out.append((x, y, unit * wgt, h))
        x += unit * wgt + GAP
    return out


# ---------- chart recipes ----------
def axis_objects(legend=False, value_axis=True, labels=False):
    o = {"legend": [{"properties": {"show": lit("true" if legend else "false"), "position": lit("'Top'")}}],
         "valueAxis": [{"properties": {"show": lit("true" if value_axis else "false"),
                                       "gridlineShow": lit("true" if value_axis else "false")}}]}
    if labels:
        o["labels"] = [{"properties": {"show": lit("true")}}]
    return o


def track_bar(page, name, pos, category, value, track_measure, title, subtitle, color_of=None, meta=None,
              sort_dir="Descending", filters=None, label_fmt=None):
    """Horizontal bar on a light-grey track with the value printed on the bar (reference 'Worst 10 cells')."""
    tr = meas(track_measure)
    dp = [series_color(tr, TRACK)]
    dp.append(series_color_by_measure(value, color_of) if color_of and color_of.startswith("Color")
              else series_color(value, color_of or BLUE))
    objects = {
        "legend": OFF(), "valueAxis": OFF(),
        "categoryAxis": [{"properties": {"labelColor": color(TEXT), "fontSize": lit("11D")}}],
        "dataPoint": dp,
        "labels": [{"properties": {"show": lit("true"), "color": color(WHITE), "fontSize": lit("10D"),
                                   "labelPosition": lit("'InsideEnd'"), "bold": lit("true")}},
                   {"properties": {"showSeries": lit("false")}, "selector": {"metadata": ref(tr)}}],
    }
    chart(page, name, "barChart", pos, {"Category": [category], "Y": [value, tr]}, title, subtitle, objects,
          sort=(value, sort_dir), filters=filters, meta=meta)


def area(page, name, pos, category, value, title, subtitle, c, meta=None):
    chart(page, name, "areaChart", pos, {"Category": [category], "Y": [value]}, title, subtitle,
          {**axis_objects(), "dataPoint": [series_color(value, c)],
           "lineStyles": [{"properties": {"strokeWidth": lit("2D"), "showMarker": lit("false")}}]}, meta=meta)


def columns(page, name, pos, category, value, title, subtitle, c=BLUE, series=None, colors=None, meta=None,
            sort=None, legend=None):
    buckets = {"Category": [category], "Y": [value]}
    dp = []
    if series:
        buckets["Series"] = [series]
        for v, cc in (colors or []):
            dp.append(value_color(series["Column"]["Expression"]["SourceRef"]["Entity"],
                                  series["Column"]["Property"], v, cc))
    else:
        dp.append(series_color(value, c))
    chart(page, name, "columnChart", pos, buckets, title, subtitle,
          {**axis_objects(legend=bool(series) if legend is None else legend), "dataPoint": dp}, sort=sort, meta=meta)


def table(page, name, pos, fields, title, subtitle=None, sort=None, filters=None, rules=None, meta=None,
          displays=None):
    objects = {"values": rules or [], "total": [{"properties": {"totals": lit("false")}}]}
    chart(page, name, "tableEx", pos, {"Values": fields}, title, subtitle, objects, sort=sort, filters=filters,
          displays=displays, meta=meta)


SLA_COLORS = [("RESOLVED_IN_SLA", GREEN), ("ON_TRACK", BLUE), ("RESOLVED_LATE", AMBER),
              ("UNASSIGNED", GREY), ("BREACHED", RED)]
FOUR = cols(4, KPI_Y, KPI_H)
FIVE = cols(5, KPI_Y, KPI_H)
ROW2 = cols(3, R2_Y, R2_H)
ROW3 = cols(3, R3_Y, R3_H)

# =====================================================================
# Page 1 Overview
P = "overview"
chrome(P, "Overview", "Is today's data healthy, and what needs attention first?", 1)
k1 = cols(4, KPI_Y, 108)
k2 = cols(4, KPI_Y + 120, 108)
kpi(P, "ov-dq", k1[0], "DQ pass rate", BLUE, "DQ Pass Rate", "UI DQ Pill", "status",
    (col("mart_dq_trend", "run_date"), meas("DQ Trend Pass Rate"), BLUE), nav="data-quality")
kpi(P, "ov-quarantine", k1[1], "Rows in quarantine", PURPLE, "Quarantined Rows", "UI Quarantine Pill", "status",
    nav="data-quality")
kpi(P, "ov-open", k1[2], "Open incidents", ORANGE, "Open Incidents", "UI Open 7d", "grey",
    (col("mart_incidents", "opened_at"), meas("Incident Count"), ORANGE), nav="incidents")
kpi(P, "ov-breached", k1[3], "SLA breached", RED, "SLA Breached", "UI SLA Pill", "status", nav="incidents")
kpi(P, "ov-risk", k2[0], "EUR at risk (data defects)", ORANGE, "EUR At Risk", "UI Defect Pill", "status",
    (col("mart_revenue_assurance_trend", "run_ts"), meas("Recon Risk Run"), ORANGE), nav="revenue-assurance",
    units="1D")
kpi(P, "ov-unpaid", k2[1], "Unpaid EUR", ORANGE, "Unpaid EUR", "UI Collection Pill", "status", nav="customer-360",
    units="1D")
kpi(P, "ov-active", k2[2], "Active customers", GREEN, "Active Customers", "UI Active Share", "grey",
    nav="customer-360")
kpi(P, "ov-drop", k2[3], "Dropped call rate", PURPLE, "Drop Rate", "UI Drop Pill", "status",
    (col("mart_network_daily", "usage_date"), meas("Drop Rate"), PURPLE), nav="network-app")
r2 = cols(3, 368, 318)
chart(P, "ov-pass-trend", "lineChart", r2[0],
      {"Category": [col("mart_dq_trend", "run_date")], "Y": [meas("DQ Trend Pass Rate"), meas("Target DQ Pass")]},
      "Pass rate by day", "Gate rules, all datasets, vs 98% target",
      {**axis_objects(legend=True), "dataPoint": [series_color(meas("DQ Trend Pass Rate"), BLUE),
                                                  series_color(meas("Target DQ Pass"), GREY)],
       "lineStyles": [{"properties": {"strokeWidth": lit("2D"), "showMarker": lit("true"),
                                      "markerSize": lit("4D")}}]},
      displays={f"{M}.DQ Trend Pass Rate": "Pass rate", f"{M}.Target DQ Pass": "Target"}, meta="=UI Runs DQ")
track_bar(P, "ov-risk-type", r2[1], col("mart_revenue_assurance", "leak_type"), meas("Gross EUR At Risk"),
          "Leak Risk Track", "EUR at risk by leak type", "Latest reconciliation run, gross", ORANGE,
          meta="=UI Runs Recon")
chart(P, "ov-drop-trend", "lineChart", r2[2],
      {"Category": [col("mart_network_daily", "usage_date")], "Y": [meas("Drop Rate"), meas("Target Drop Rate")]},
      "Dropped call rate per day", "Voice calls, vs 2% limit",
      {**axis_objects(legend=True), "dataPoint": [series_color(meas("Drop Rate"), ORANGE),
                                                  series_color(meas("Target Drop Rate"), GREY)]},
      displays={f"{M}.Drop Rate": "Drop rate", f"{M}.Target Drop Rate": "Limit"}, meta="=UI Days Network")
r3 = cols(2, 706, 318, weights=[2, 1])
table(P, "ov-attention", r3[0],
      [col("Attention", "Priority"), col("Attention", "Area"), col("Attention", "Item"), col("Attention", "Issue")],
      "Needs attention first", "Failing DQ rules, breached or unassigned incidents, failing revenue checks",
      sort=(col("Attention", "Priority"), "Ascending"),
      rules=cell_rule("Color Attention", "Font Attention", col("Attention", "Priority")), meta="=UI Attention Count")
columns(P, "ov-priority", r3[1], col("mart_incidents", "priority"), meas("Incident Count"),
        "Incidents by priority", "Count, legend = SLA status", series=col("mart_incidents", "sla_status"),
        colors=SLA_COLORS, sort=(col("mart_incidents", "priority"), "Ascending"), meta="=UI Incidents Total")

# =====================================================================
# Page 2 Data Quality
P = "data-quality"
chrome(P, "Data Quality", "Which datasets and rules fail, is it getting better, how many rows wait in quarantine?", 2,
       pills=[("Dataset", "mart_dq_health", "dataset", 250, "Dropdown"),
              ("Dimension", "mart_dq_health", "dimension", 250, "Dropdown")])
kpi(P, "dq-pass", FOUR[0], "DQ pass rate", BLUE, "DQ Pass Rate", "UI DQ Pill", "status",
    (col("mart_dq_trend", "run_date"), meas("DQ Trend Pass Rate"), BLUE))
kpi(P, "dq-failing", FOUR[1], "Failing rules", RED, "Failing Rules", "UI Failing Pill", "status")
kpi(P, "dq-quarantine", FOUR[2], "Quarantined rows", PURPLE, "Quarantined Rows", "UI Quarantine Pill", "status")
kpi(P, "dq-oldest", FOUR[3], "Oldest quarantined row (days)", ORANGE, "Oldest Quarantine Age Days",
    "UI Oldest Note", "grey")
D3 = cols(3, R2_Y, R2_H, weights=[1, 1.75, 0.95])
chart(P, "dq-fail-dataset", "clusteredBarChart", D3[0],
      {"Category": [col("mart_dq_health", "dataset")], "Y": [meas("DQ Failure Rate")]},
      "Failure rate by dataset", "Failed / checked rows, worst first, red above 2%",
      {"legend": OFF(), "valueAxis": OFF(),
       "categoryAxis": [{"properties": {"labelColor": color(TEXT), "fontSize": lit("10D")}}],
       "dataPoint": [{"properties": {"fill": {"solid": {"color": {"expr": meas("Color Failure")}}}},
                      "selector": ALL_POINTS}],
       "labels": [{"properties": {"show": lit("true"), "color": color(TEXT), "fontSize": lit("10D"),
                                  "labelPosition": lit("'OutsideEnd'")}}]},
      sort=(meas("DQ Failure Rate"), "Descending"), meta="=UI Datasets DQ")
chart(P, "dq-heatmap", "pivotTable", D3[1],
      {"Rows": [col("mart_dq_trend", "dataset")], "Columns": [col("mart_dq_trend", "dimension")],
       "Values": [meas("DQ Trend Pass Rate")]},
      "Dataset x dimension", "Pass rate: green 98%+, amber 90-98%, red below 90%",
      {"values": [{"properties": {"backColor": {"solid": {"color": {"expr": meas("Color Matrix")}}},
                                  "fontSize": lit("10D")},
                   "selector": {**ALL_POINTS, "metadata": f"{M}.DQ Trend Pass Rate"}}],
       "columnHeaders": [{"properties": {"fontSize": lit("10D"), "wordWrap": lit("true")}}],
       "rowHeaders": [{"properties": {"fontSize": lit("10D")}}],
       "subTotals": [{"properties": {"rowSubtotals": lit("false"), "columnSubtotals": lit("false")}}],
       "columnFormatting": [{"properties": {"autoSizeColumnWidth": lit("true")}}]})
chart(P, "dq-pass-trend", "lineChart", D3[2],
      {"Category": [col("mart_dq_trend", "run_date")], "Y": [meas("DQ Trend Pass Rate"), meas("Target DQ Pass")]},
      "Pass rate over time", "vs 98% target",
      {**axis_objects(legend=True), "dataPoint": [series_color(meas("DQ Trend Pass Rate"), BLUE),
                                                  series_color(meas("Target DQ Pass"), GREY)],
       "lineStyles": [{"properties": {"strokeWidth": lit("2D"), "showMarker": lit("true")}}]},
      displays={f"{M}.DQ Trend Pass Rate": "Pass rate", f"{M}.Target DQ Pass": "Target"}, meta="=UI Runs DQ")
q = cols(2, R3_Y, R3_H, weights=[1, 2])
chart(P, "dq-quarantine", "barChart", q[0],
      {"Category": [col("mart_quarantine", "dataset")], "Y": [meas("Quarantined Rows")],
       "Series": [col("mart_quarantine", "quarantine_status")]},
      "Quarantine by dataset", "Rows waiting, by quarantine status, most first",
      {**axis_objects(legend=True), "categoryAxis": [{"properties": {"labelColor": color(TEXT),
                                                                     "fontSize": lit("10D")}}]},
      sort=(meas("Quarantined Rows"), "Descending"), meta="=UI Quarantine Datasets")
table(P, "dq-failing-rules", q[1],
      [col("mart_dq_health", c) for c in ["dataset", "rule_id", "check_name", "scope"]]
      + [agg("mart_dq_health", "rows_failed")]
      + [col("mart_dq_health", c) for c in ["status", "severity", "detail"]],
      "Failing rules", "Latest result per rule, status is not PASS, most failed rows first",
      sort=(agg("mart_dq_health", "rows_failed"), "Descending"),
      filters=[filter_not_in("mart_dq_health", "status", ["PASS"])],
      rules=cell_rule("Color DQ Status", "Font DQ Status", col("mart_dq_health", "status")),
      displays={"Sum(mart_dq_health.rows_failed)": "rows_failed"})

# =====================================================================
# Page 3 Revenue Assurance
P = "revenue-assurance"
chrome(P, "Revenue Assurance", "How many EUR leak between systems, where, and which cases must be investigated?", 3,
       pills=[("Defect or business", "mart_revenue_assurance", "is_data_defect", 300, "Dropdown")])
kpi(P, "ra-gross", FIVE[0], "EUR at risk", ORANGE, "Gross EUR At Risk", "UI Gross Note", "amber",
    (col("mart_revenue_assurance_trend", "run_ts"), meas("Recon Risk Run"), ORANGE), units="1D")
kpi(P, "ra-defect", FIVE[1], "EUR at risk, data defects", RED, "EUR At Risk", "UI Defect Pill", "status",
    units="1D")
kpi(P, "ra-mismatched", FIVE[2], "Mismatched rows", PURPLE, "Mismatched Rows", "UI Mismatch Checks", "grey")
kpi(P, "ra-failing", FIVE[3], "Checks failing", RED, "Checks Failing", "UI Checks Total", "red")
kpi(P, "ra-cases", FIVE[4], "Cases to investigate", BLUE, "Cases To Investigate", "UI Latest Run", "blue")
r2 = cols(2, R2_Y, R2_H)
track_bar(P, "ra-risk-type", r2[0], col("mart_revenue_assurance", "leak_type"), meas("Gross EUR At Risk"),
          "Leak Risk Track", "EUR at risk by leak type", "Click a bar to filter the checks and cases", ORANGE,
          meta="=UI Checks Total")
area(P, "ra-trend", r2[1], col("mart_revenue_assurance_trend", "run_ts"), meas("Recon Risk Run"),
     "EUR at risk per run", "Total of all checks; click a leak type to see one check", ORANGE, meta="=UI Runs Recon")
r3 = cols(2, R3_Y, R3_H)
table(P, "ra-checks", r3[0],
      [col("mart_revenue_assurance", c) for c in ["check_id", "leak_type", "source_a", "source_b"]]
      + [agg("mart_revenue_assurance", c) for c in ["rows_checked", "rows_mismatched", "amount_at_risk_eur"]]
      + [col("mart_revenue_assurance", c) for c in ["status", "severity"]],
      "Checks R1 to R10", "Latest run, R10 is business (unpaid), not a data defect",
      sort=(col("mart_revenue_assurance", "check_id"), "Ascending"),
      rules=cell_rule("Color Recon Status", "Font Recon Status", col("mart_revenue_assurance", "status")),
      displays={f"Sum(mart_revenue_assurance.{c})": c for c in ["rows_checked", "rows_mismatched",
                                                               "amount_at_risk_eur"]})
table(P, "ra-cases", r3[1],
      [col("mart_recon_mismatches", c) for c in ["check_id", "entity_type", "entity_key", "value_a", "value_b"]]
      + [agg("mart_recon_mismatches", "diff"), agg("mart_recon_mismatches", "amount_at_risk_eur"),
         col("mart_recon_mismatches", "reason")],
      "Case list", "What the billing team investigates, largest EUR first",
      sort=(agg("mart_recon_mismatches", "amount_at_risk_eur"), "Descending"),
      displays={"Sum(mart_recon_mismatches.diff)": "diff",
                "Sum(mart_recon_mismatches.amount_at_risk_eur)": "amount_at_risk_eur"})

# =====================================================================
# Page 4 Incidents
P = "incidents"
chrome(P, "Incidents", "Who owns each incident, how late is it, does the team meet its deadlines?", 4,
       pills=[("Priority", "mart_incidents", "priority", 190, "Dropdown"),
              ("Team", "mart_incidents", "team", 200, "Dropdown"),
              ("Dataset", "mart_incidents", "dataset", 220, "Dropdown"),
              ("Status", "mart_incidents", "status", 200, "Dropdown")])
kpi(P, "in-open", FOUR[0], "Open", ORANGE, "Open Incidents", "UI Open 7d", "grey",
    (col("mart_incidents", "opened_at"), meas("Incident Count"), ORANGE))
kpi(P, "in-breached", FOUR[1], "Breached", RED, "SLA Breached", "UI SLA Pill", "status")
kpi(P, "in-resolved", FOUR[2], "Resolved in SLA", GREEN, "Resolved In SLA", "UI Compliance Pill", "status")
kpi(P, "in-ack", FOUR[3], "Avg minutes to ack", BLUE, "Avg Minutes To Ack", "UI Ack Note", "blue", decimals=1)
columns(P, "in-priority", ROW2[0], col("mart_incidents", "priority"), meas("Open Incidents"), "Open by priority",
        "Open incidents, legend = SLA status", series=col("mart_incidents", "sla_status"), colors=SLA_COLORS,
        sort=(col("mart_incidents", "priority"), "Ascending"))
track_bar(P, "in-team", ROW2[1], col("mart_incidents", "team"), meas("Open Incidents"), "Team Workload Track",
          "Workload by team", "Open incidents per team", BLUE, meta="=UI Teams")
chart(P, "in-sla", "donutChart", ROW2[2],
      {"Category": [col("mart_incidents", "sla_status")], "Y": [meas("Incident Count")]},
      "SLA outcome", "All incidents", {
          "dataPoint": [value_color("mart_incidents", "sla_status", v, c) for v, c in SLA_COLORS],
          "legend": [{"properties": {"show": lit("true"), "position": lit("'Right'")}}],
          "labels": [{"properties": {"show": lit("true"), "labelStyle": lit("'Percent of total'")}}]},
      meta="=UI Incidents Total")
r3 = cols(2, R3_Y, R3_H, weights=[2, 1])
table(P, "in-list", r3[0],
      [col("mart_incidents", c) for c in ["incident_id", "priority", "dataset", "check_name", "description",
                                         "owner", "team", "status", "due_at"]]
      + [agg("mart_incidents", "escalation_level", 4), agg("mart_incidents", "open_hours", 4),
         col("mart_incidents", "sla_status")],
      "Incident list", "Soonest deadline first, BREACHED in red",
      sort=(col("mart_incidents", "due_at"), "Ascending"),
      rules=cell_rule("Color SLA Status", "Font SLA Status", col("mart_incidents", "sla_status")),
      displays={"Max(mart_incidents.escalation_level)": "escalation_level",
                "Max(mart_incidents.open_hours)": "open_hours"})
columns(P, "in-opened", r3[1], col("mart_incidents", "opened_at"), meas("Incident Count"),
        "Incidents opened per day", "Count", BLUE, meta="=UI Incidents Total")

# =====================================================================
# Page 5 Customer 360
P = "customer-360"
chrome(P, "Customer 360", "Who has paid, who owes us money, which customers have problems?", 5,
       pills=[("Status", "mart_customer_360", "status", 200, "Dropdown"),
              ("City", "mart_customer_360", "city", 210, "Dropdown"),
              ("Plan", "mart_customer_360", "plan_name", 220, "Dropdown")])
kpi(P, "cu-count", FIVE[0], "Customers", BLUE, "Customer Count", "UI Active Share", "blue")
kpi(P, "cu-billed", FIVE[1], "Billed EUR", PURPLE, "Billed EUR", "UI Invoices", "grey", units="1D")
kpi(P, "cu-paid", FIVE[2], "Paid EUR", GREEN, "Paid EUR", "UI Collection Pill", "status", units="1D")
kpi(P, "cu-unpaid", FIVE[3], "Unpaid EUR", ORANGE, "Unpaid EUR", "UI Unpaid Owe", "grey", units="1D")
kpi(P, "cu-active", FIVE[4], "Active customers", GREEN, "Active Customers", "UI Plans", "grey")
C4 = cols(4, R2_Y, R2_H)
chart(P, "cu-aging", "columnChart", C4[0],
      {"Category": [col("mart_customer_360", "payment_age_band")], "Y": [meas("Unpaid EUR")]},
      "Unpaid EUR by payment age", "Days since last payment, older is darker",
      {**axis_objects(), "dataPoint": [{"properties": {"fill": {"solid": {"color": {"expr": meas("Color Aging")}}}},
                                        "selector": ALL_POINTS}]},
      sort=(col("mart_customer_360", "payment_age_band"), "Ascending"),
      filters=[filter_not_in("mart_customer_360", "payment_age_band", ["Paid up"])])
chart(P, "cu-breakdown", "barChart", C4[2],
      {"Category": [col("mart_customer_360", "status"), col("mart_customer_360", "city"),
                    col("mart_customer_360", "plan_name")], "Y": [meas("Customer Count")]},
      "Customers by status / city / plan", "Use the drill arrows to switch level",
      {**axis_objects(value_axis=False, labels=True), "dataPoint": [series_color(meas("Customer Count"), BLUE)]},
      sort=(meas("Customer Count"), "Descending"), meta="=UI Customers Shown")
track_bar(P, "cu-unpaid-plan", C4[1], col("mart_customer_360", "plan_name"), meas("Unpaid EUR"),
          "Unpaid Plan Track", "Unpaid EUR by plan", "Billed minus paid", ORANGE, meta="=UI Plans")
chart(P, "cu-usage", "scatterChart", C4[3],
      {"Category": [col("mart_customer_360", "customer_id")],
       "X": [agg("mart_customer_360", "voice_minutes_used")], "Y": [agg("mart_customer_360", "data_mb_used")],
       "Tooltips": [col("mart_customer_360", "plan_name")]},
      "Plan usage", "Voice min (x) vs data MB (y); plan filter compares plans",
      {**axis_objects(), "dataPoint": [{"properties": {"defaultColor": color(BLUE)}}]})
r3 = cols(2, R3_Y, R3_H)
table(P, "cu-top-unpaid", r3[0],
      [col("mart_customer_360", c) for c in ["customer_id", "name_masked", "city", "plan_name"]]
      + [agg("mart_customer_360", c) for c in ["billed_eur", "paid_eur", "unpaid_eur"]]
      + [col("mart_customer_360", "last_payment_at")],
      "Top 20 customers by unpaid EUR", "Right-click a customer > Drill through for the profile",
      sort=(agg("mart_customer_360", "unpaid_eur"), "Descending"),
      filters=[filter_top_n("mart_customer_360", "customer_id", 20, "Unpaid EUR")],
      displays={f"Sum(mart_customer_360.{c})": c for c in ["billed_eur", "paid_eur", "unpaid_eur"]})
table(P, "cu-problems", r3[1],
      [col("mart_customer_360", "customer_id")]
      + [agg("mart_customer_360", c) for c in ["dropped_calls", "app_crashes", "plan_changes"]]
      + [col("mart_customer_360", c) for c in ["last_login_at", "last_network_activity_at"]],
      "Customers with problems", "Most dropped calls first",
      sort=(agg("mart_customer_360", "dropped_calls"), "Descending"),
      displays={f"Sum(mart_customer_360.{c})": c for c in ["dropped_calls", "app_crashes", "plan_changes"]})

# Drill-through profile (hidden)
P = "customer-profile"
chrome(P, "Customer profile", "Everything about one customer. Names, phone and email are masked.")
groups = [
    ("Customer", ["customer_id", "name_masked", "email_masked", "msisdn_masked", "city", "country", "status",
                  "created_at"]),
    ("Plan and billing", ["plan_name", "monthly_fee", "plan_data_gb", "plan_voice_minutes", "invoices",
                          "billed_eur", "paid_eur", "unpaid_eur", "last_payment_at"]),
    ("Network use", ["voice_minutes_used", "sms_count", "data_mb_used", "dropped_calls",
                     "last_network_activity_at"]),
    ("App and partner", ["app_events", "app_crashes", "plan_changes", "last_login_at", "partner_amount_eur"]),
]
for i, (pos, (lb, fields)) in enumerate(zip(cols(4, KPI_Y, 904), groups)):
    chart(P, f"profile-{i}", "multiRowCard", pos, {"Values": [col("mart_customer_360", c) for c in fields]}, lb,
          objects={"card": [{"properties": {"barShow": lit("true"), "barColor": color(BLUE)}}],
                   "dataLabels": [{"properties": {"color": color(TEXT), "fontSize": lit("12D")}}],
                   "categoryLabels": [{"properties": {"color": color(SUB), "fontSize": lit("9D")}}]})

# =====================================================================
# Page 6 Network & App  (the reference image)
P = "network-app"
chrome(P, "Network & App", "Where do calls drop, how does the app behave, and what does partner traffic cost?", 6,
       pills=[("Event type", "mart_network_daily", "event_type", 190, "Dropdown"),
              ("App version", "mart_app_usage", "app_version", 200, "Dropdown"),
              ("Date range", "mart_network_daily", "usage_date", 330, "Between")])
nd = "mart_network_daily"
kpi(P, "nw-records", FIVE[0], "Records", BLUE, "Network Records", "UI Records Delta", "blue",
    (col(nd, "usage_date"), meas("Network Records"), BLUE))
kpi(P, "nw-voice", FIVE[1], "Voice minutes", GREEN, "Voice Minutes", "UI Voice Delta", "blue",
    (col(nd, "usage_date"), meas("Voice Minutes"), GREEN))
kpi(P, "nw-data", FIVE[2], "Data", PURPLE, "Data GB", "UI Data Delta", "blue",
    (col(nd, "usage_date"), meas("Data GB"), PURPLE))
kpi(P, "nw-drop", FIVE[3], "Drop rate", ORANGE, "Drop Rate", "UI Drop Pill", "status",
    (col(nd, "usage_date"), meas("Drop Rate"), ORANGE), decimals=1)
kpi(P, "nw-partner", FIVE[4], "Partner cost, unknown customer", AMBER, "Unknown Partner Cost EUR",
    "UI Partner Pill", "status", (col("mart_partner_usage", "period_start"), meas("Unknown Partner Cost EUR"),
                                    AMBER), units="1D")
columns(P, "nw-records-day", ROW2[0], col(nd, "usage_date"), meas("Network Records M"), "Records per day by type",
        "Millions", series=col(nd, "event_type"),
        colors=[("VOICE", BLUE), ("DATA", GREEN), ("SMS", PURPLE)], meta="=UI Days Network")
area(P, "nw-drop-day", ROW2[1], col(nd, "usage_date"), meas("Drop Rate"), "Dropped call rate per day",
     "Voice calls only", ORANGE, meta="=UI Days Network")
track_bar(P, "nw-cells", ROW2[2], col("mart_cell_quality", "cell_id"), meas("Cell Drop Rate"), "Cell Drop Track",
          "Worst 10 cells", "Drop rate, minimum 20 voice calls", ORANGE, meta="top 10 shown",
          filters=[filter_top_n("mart_cell_quality", "cell_id", 10, "Cell Drop Rate")])
columns(P, "nw-app-events", ROW3[0], col("mart_app_usage", "event_date"), meas("App Events K"), "App events per day",
        "Thousands", BLUE, meta="=UI Days App")
track_bar(P, "nw-crash", ROW3[1], col("mart_app_usage", "app_version"), meas("Crash Share"), "Crash Share Track",
          "Crash share by app version", "Crashes / events, red above the 2% limit", "Color Crash Share",
          meta="=UI Versions App")
columns(P, "nw-partner-cost", ROW3[2], col("mart_partner_usage", "period_start"), meas("Partner Cost K"),
        "Partner cost by service per month", "EUR thousands", series=col("mart_partner_usage", "service"),
        meta="=UI Months Partner")


# =====================================================================
PAGE_META = [("overview", "Overview"), ("data-quality", "Data Quality"), ("revenue-assurance", "Revenue Assurance"),
             ("incidents", "Incidents"), ("customer-360", "Customer 360"), ("customer-profile", "Customer Profile"),
             ("network-app", "Network & App")]


def dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False)


old_profile = json.load(open(os.path.join(PAGES, "customer-profile", "page.json"), encoding="utf-8"))
shutil.rmtree(PAGES)
for name, display in PAGE_META:
    if name == "customer-profile":
        page = old_profile
        page["displayName"] = display
    else:
        page = {"$schema": PAGE_SCHEMA, "name": name, "displayName": display}
    page.update({"displayOption": "FitToPage", "height": 1080, "width": 1920})
    page["objects"] = {"background": [{"properties": {"color": color(BG), "transparency": lit("0D")}}],
                       "outspace": [{"properties": {"color": color(BG), "transparency": lit("0D")}}]}
    dump(os.path.join(PAGES, name, "page.json"), page)
names = set()
for page, name, doc in VISUALS:
    assert (page, name) not in names, name
    names.add((page, name))
    dump(os.path.join(PAGES, page, "visuals", name, "visual.json"), doc)
dump(os.path.join(PAGES, "pages.json"), {
    "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.1.0/schema.json",
    "pageOrder": [n for n, _ in PAGE_META], "activePageName": "network-app"})

theme_src = os.path.join(ROOT, "..", "theme", "sentinel_theme.json")
reg_dir = os.path.join(REPORT, "StaticResources", "RegisteredResources")
os.makedirs(reg_dir, exist_ok=True)
shutil.copy(theme_src, os.path.join(reg_dir, "sentinel_theme.json"))
rep_path = os.path.join(DEF, "report.json")
rep = json.load(open(rep_path, encoding="utf-8"))
rep["themeCollection"]["customTheme"] = {
    "name": "sentinel_theme.json",
    "reportVersionAtImport": rep["themeCollection"]["baseTheme"]["reportVersionAtImport"],
    "type": "RegisteredResources"}
rep["resourcePackages"] = [p for p in rep["resourcePackages"] if p["type"] != "RegisteredResources"] + [{
    "name": "RegisteredResources", "type": "RegisteredResources",
    "items": [{"name": "sentinel_theme.json", "path": "sentinel_theme.json", "type": "CustomTheme"}]}]
dump(rep_path, rep)
print(f"wrote {len(VISUALS)} visuals on {len(PAGE_META)} pages")
