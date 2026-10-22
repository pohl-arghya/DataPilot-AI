"""DataPilot AI - local Flask app.  Run:  python app.py  ->  http://127.0.0.1:5000
Uploaded files are processed in memory only; nothing is written to disk."""
import io, json, os, re, warnings
import numpy as np
import pandas as pd
from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

BASE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
STATE = {"df": None, "name": None, "sample": False, "analysis": None}  # single local user

ALIASES = {
    "revenue": ["revenue", "sales", "amount", "total sales", "turnover", "total revenue", "sales amount"],
    "profit": ["profit", "net income", "gross profit", "net profit"],
    "date": ["date", "order date", "timestamp", "transaction date", "invoice date"],
    "product": ["product", "product name", "item", "sku", "item name"],
    "category": ["category", "segment", "department", "type", "product category"],
    "quantity": ["quantity", "qty", "units", "units sold"],
}
NUMERIC = ("revenue", "profit", "quantity")


class UserError(Exception):
    def __init__(self, msg, code=422):
        super().__init__(msg); self.msg, self.code = msg, code


# ---------- helpers ----------
def norm(s): return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()
def _n(x): return f"{x:,.0f}" if abs(x) >= 100 else f"{x:,.2f}"

def numeric(s):
    if pd.api.types.is_numeric_dtype(s): return s
    return pd.to_numeric(s.astype(str).str.replace(r"[,$€£₹\s%]", "", regex=True), errors="coerce")

def todate(s):
    if pd.api.types.is_datetime64_any_dtype(s): return s
    if pd.api.types.is_numeric_dtype(s): return pd.Series(pd.NaT, index=s.index)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try: return pd.to_datetime(s, errors="coerce", format="mixed")
        except (TypeError, ValueError): return pd.to_datetime(s, errors="coerce")

def usable(s, role):
    nn = s.dropna()
    if nn.empty: return 0.0
    if role in NUMERIC: return float(numeric(nn).notna().mean())
    if role == "date": return float(todate(nn).notna().mean())
    return 1.0

def load_frame(name, raw):
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ("csv", "xlsx", "xls"):
        raise UserError("Unsupported file type. Upload a .csv, .xlsx or .xls file.", 415)
    if not raw: raise UserError("The file is empty.")
    try:
        if ext == "csv":
            try: df = pd.read_csv(io.BytesIO(raw))
            except UnicodeDecodeError: df = pd.read_csv(io.BytesIO(raw), encoding="latin-1")
        else:
            df = pd.read_excel(io.BytesIO(raw), engine="openpyxl" if ext == "xlsx" else None)
    except pd.errors.EmptyDataError:
        raise UserError("The file contains no data.")
    except ImportError:
        raise UserError("Reading .xls files needs the 'xlrd' package: pip install xlrd")
    except Exception:
        raise UserError("The file could not be read. Check that it is a valid, uncorrupted CSV or Excel file.")
    df.columns = [str(c).strip() for c in df.columns]
    if df.shape[0] == 0 or df.shape[1] == 0:
        raise UserError("The file has no data rows. A header row alone is not enough.")
    return df


# ---------- column detection ----------
def detect(df):
    mapping, notes = {}, []
    for role, names in ALIASES.items():
        exact = list(dict.fromkeys(c for n in names for c in df.columns if norm(c) == n))
        loose = [c for c in df.columns if c not in exact and any(
            (n in norm(c)) if " " in n else (n in norm(c).split()) for n in names)]
        pick = next((c for c in exact if usable(df[c], role) >= 0.8), None)
        if exact and pick is None:
            notes.append(f"'{exact[0]}' looks like {role}, but its values are not usable as {role}. Choose a column in Settings.")
        elif len(exact) > 1:
            notes.append(f"Several columns could be {role} ({', '.join(exact)}). Using '{pick}'; change it in Settings.")
        elif not exact and loose:
            notes.append(f"No exact {role} column found. Possible matches: {', '.join(loose[:3])}. Not used automatically; select one in Settings if appropriate.")
        mapping[role] = pick
    return mapping, notes

def prep(df, m):
    d = pd.DataFrame(index=df.index)
    for r in NUMERIC:
        if m.get(r): d[r] = numeric(df[m[r]])
    if m.get("date"): d["date"] = todate(df[m["date"]])
    for r in ("product", "category"):
        if m.get(r): d[r] = df[m[r]].astype("string")
    return d


# ---------- data quality (kept separate from insights) ----------
def quality(df, m):
    miss = df.isna().sum(); total = int(miss.sum()); dup = int(df.duplicated().sum()); W = []
    if total:
        top = miss[miss > 0].sort_values(ascending=False).head(4)
        W.append(("warn", f"{total:,} missing cells ({100*total/df.size:.1f}% of all cells). Most affected: " +
                  ", ".join(f"{c} ({int(v):,})" for c, v in top.items()) + "."))
    if dup: W.append(("warn", f"{dup:,} duplicate rows (exact copies of an earlier row). They are included in every figure; nothing was removed."))
    empty = [c for c in df.columns if df[c].isna().all()]
    if empty: W.append(("warn", f"Empty columns: {', '.join(empty)}."))
    shown = 0
    for c in df.columns:
        s = df[c]; nn = s.dropna()
        if nn.empty or pd.api.types.is_numeric_dtype(s) or pd.api.types.is_datetime64_any_dtype(s) or pd.api.types.is_bool_dtype(s): continue
        sh = float(numeric(nn).notna().mean())
        if sh == 1.0 and shown < 4:
            W.append(("info", f"'{c}' is stored as text but every value looks numeric. If you expect to calculate with it, check its format.")); shown += 1
        elif 0.6 <= sh < 1.0 and shown < 4:
            bad = numeric(nn).isna(); W.append(("warn", f"'{c}' is mostly numeric, but {int(bad.sum()):,} values are not numbers (e.g. '{nn[bad].iloc[0]}').")); shown += 1
    dc = m.get("date")
    for c in df.columns:
        s = df[c]; nn = s.dropna()
        if nn.empty or pd.api.types.is_numeric_dtype(s) or pd.api.types.is_datetime64_any_dtype(s): continue
        if c == dc or set(norm(c).split()) & {"date", "time", "timestamp"}:
            bad = todate(nn).isna()
            if bad.any(): W.append(("warn", f"'{c}': {int(bad.sum()):,} values are not valid dates (e.g. '{nn[bad].iloc[0]}')."))
    if not W: W.append(("ok", "No data-quality issues were found by the checks run (missing cells, duplicates, empty columns, text-stored numbers, invalid dates)."))
    return {"missing_cells": total, "duplicate_rows": dup, "warnings": [{"level": l, "text": t} for l, t in W]}


# ---------- analysis ----------
def monthly(d):
    if not {"revenue", "date"} <= set(d.columns): return None
    t = d.dropna(subset=["revenue", "date"])
    if t.empty: return None
    g = t.groupby(t["date"].dt.to_period("M"))["revenue"].sum()
    return g.reindex(pd.period_range(g.index.min(), g.index.max(), freq="M"))

def by(d, key, val="revenue"):
    return d.dropna(subset=[key, val]).groupby(key)[val].sum().sort_values(ascending=False)

def kpis(df, d, m):
    K = []
    def add(key, label, val, kind, note): K.append({"key": key, "label": label, "value": val, "kind": kind, "note": note})
    R, P = m.get("revenue"), m.get("profit")
    if R: add("revenue", "Total revenue", float(d.revenue.sum()), "num", f"Sum of '{R}' ({int(d.revenue.notna().sum()):,} valid values)")
    else: add("revenue", "Total revenue", None, "num", "No revenue or sales column was detected. Choose one in Settings.")
    if P: add("profit", "Total profit", float(d.profit.sum()), "num", f"Sum of '{P}' ({int(d.profit.notna().sum()):,} valid values)")
    else: add("profit", "Total profit", None, "num", "No profit column was detected. Choose one in Settings.")
    if R and P:
        b = d.dropna(subset=["revenue", "profit"]); r = float(b.revenue.sum())
        if r: add("margin", "Profit margin", float(b.profit.sum()) / r * 100, "pct", "Profit ÷ revenue, over rows that have both values")
        else: add("margin", "Profit margin", None, "pct", "Revenue sums to zero, so a margin cannot be calculated.")
    else: add("margin", "Profit margin", None, "pct", "Needs both a revenue and a profit column.")
    add("records", "Total records", len(df), "num", f"{len(df.columns)} columns")
    return K

def charts(d, m):
    C = {}
    def na(k, title, why): C[k] = {"available": False, "title": title, "reason": why}
    def ok(k, typ, title, labels, ds, x, y): C[k] = {"available": True, "type": typ, "title": title, "labels": labels, "datasets": ds, "xlabel": x, "ylabel": y}
    R, P, PR, CA = m.get("revenue"), m.get("profit"), m.get("product"), m.get("category")
    g = monthly(d)
    if g is not None and g.notna().sum() >= 2:
        ok("trend", "line", f"{R} by month", [str(p) for p in g.index], [{"label": R, "data": [None if pd.isna(v) else round(float(v), 2) for v in g]}], "Month", R)
    else: na("trend", "Revenue over time", "Needs a date column and a revenue column with at least two months of valid data.")
    if CA and R and len(by(d, "category")):
        g = by(d, "category").head(12); ok("category", "bar", f"{R} by {CA}", g.index.tolist(), [{"label": R, "data": [round(float(v), 2) for v in g]}], CA, R)
    else: na("category", "Revenue by category", "Needs a category column and a revenue column.")
    if PR and R and len(by(d, "product")):
        g = by(d, "product").head(10); ok("products", "hbar", f"Top {len(g)} by {R}", g.index.tolist(), [{"label": R, "data": [round(float(v), 2) for v in g]}], PR, R)
    else: na("products", "Top products", "Needs a product column and a revenue column.")
    if CA and R and P and len(d.dropna(subset=["category", "revenue", "profit"])):
        t = d.dropna(subset=["category", "revenue", "profit"]).groupby("category")[["revenue", "profit"]].sum().sort_values("revenue", ascending=False).head(12)
        ok("profit_cat", "bar", f"{R} and {P} by {CA}", t.index.tolist(),
           [{"label": R, "data": t.revenue.round(2).tolist()}, {"label": P, "data": t.profit.round(2).tolist()}], CA, "Amount")
    else: na("profit_cat", "Profit comparison", "Needs category, revenue and profit columns.")
    v = d["revenue"].dropna() if R else pd.Series(dtype=float)
    if len(v) >= 5 and v.nunique() > 1:
        cnt, e = np.histogram(v, bins=10)
        ok("hist", "bar", f"Distribution of {R} per record", [f"{_n(e[i])} to {_n(e[i+1])}" for i in range(10)], [{"label": "Records", "data": cnt.tolist()}], R, "Number of records")
    else: na("hist", "Distribution", "Needs a numeric revenue column with at least five varied values.")
    return C

def insights(d, m):
    I, U = [], []
    def add(kind, text, basis): I.append({"kind": kind, "text": text, "basis": basis})
    R, P, PR, CA = m.get("revenue"), m.get("profit"), m.get("product"), m.get("category")
    if not R: U.append({"title": "Revenue insights", "reason": "No revenue column is selected."}); return I, U
    if PR and len(by(d, "product")):
        g = by(d, "product"); tot = g.sum()
        add("fact", f"'{g.index[0]}' is the highest-revenue product: {_n(g.iloc[0])}, {100*g.iloc[0]/tot:.1f}% of total {R}." +
            (f" The lowest is '{g.index[-1]}' at {_n(g.iloc[-1])}." if len(g) > 1 else ""), f"Sum of {R} grouped by {PR} ({len(g)} products)")
    else: U.append({"title": "Product ranking", "reason": "Needs a product column."})
    if CA and len(by(d, "category")):
        g = by(d, "category"); tot = g.sum()
        add("fact", f"'{g.index[0]}' is the strongest category: {_n(g.iloc[0])} ({100*g.iloc[0]/tot:.1f}% of total {R})." +
            (f" The weakest is '{g.index[-1]}' at {_n(g.iloc[-1])}." if len(g) > 1 else ""), f"Sum of {R} grouped by {CA}")
    else: U.append({"title": "Category comparison", "reason": "Needs a category column."})
    g = monthly(d)
    if g is not None and g.notna().sum() >= 2:
        v = g.dropna(); add("fact", f"Best month: {v.idxmax()} ({_n(v.max())}). Weakest month: {v.idxmin()} ({_n(v.min())}).", f"Monthly sums of {R}")
        a, b = g.iloc[-2], g.iloc[-1]
        if pd.notna(a) and pd.notna(b) and a != 0:
            add("fact", f"{g.index[-1]} {R} was {_n(b)}, a {abs(100*(b-a)/a):.1f}% {'increase' if b >= a else 'decrease'} from {g.index[-2]} ({_n(a)}).", "Last two consecutive months")
            add("context", "The latest month may be only partly covered by the data, which would distort this comparison. Check the last date in your file.", "Possible explanation, not calculated")
        l = g.iloc[-4:]
        if len(l) == 4 and l.notna().all() and (l.diff().dropna() < 0).all():
            add("fact", f"{R} fell in each of the last three months: {' → '.join(_n(x) for x in l)}.", "Last four consecutive months")
            add("context", "The data shows the decline but not its cause. Seasonality, stock or pricing changes are possibilities worth checking.", "Possible explanation, not calculated")
    else: U.append({"title": "Monthly trend", "reason": "Needs valid dates and revenue across at least two months."})
    v = d.revenue.dropna()
    if len(v):
        add("fact", f"Average {R} per record is {_n(v.mean())} (median {_n(v.median())}).", f"Mean and median of {R} over {len(v):,} records. A record is not necessarily one order.")
        if m.get("quantity"):
            b = d.dropna(subset=["revenue", "quantity"]); q = b.quantity.sum()
            if q: add("fact", f"Revenue per unit is {_n(b.revenue.sum()/q)}.", f"Sum of {R} ÷ sum of {m['quantity']}")
        q1, q3 = v.quantile(.25), v.quantile(.75); hi = q3 + 1.5 * (q3 - q1); o = v[v > hi]
        if len(o): add("fact", f"{len(o):,} records have unusually high {R} (above {_n(hi)}); the largest is {_n(o.max())}.", "Tukey rule: values above Q3 + 1.5 × IQR")
        else: add("fact", f"No unusually high {R} values were found.", "Tukey rule: values above Q3 + 1.5 × IQR")
    if P and CA:
        b = d.dropna(subset=["category", "revenue", "profit"]).groupby("category")[["revenue", "profit"]].sum()
        b = b[b.revenue != 0]
        if len(b) > 1:
            mg = (b.profit / b.revenue * 100).sort_values(ascending=False)
            add("fact", f"Profit margin is highest in '{mg.index[0]}' ({mg.iloc[0]:.1f}%) and lowest in '{mg.index[-1]}' ({mg.iloc[-1]:.1f}%).", f"Sum of {P} ÷ sum of {R}, per {CA}")
    elif P: U.append({"title": "Margin by category", "reason": "Needs a category column."})
    if P:
        n = int((d.profit.dropna() < 0).sum())
        if n: add("fact", f"{n:,} records have negative {P}.", f"Count of {P} < 0")
    else: U.append({"title": "Profit insights", "reason": "No profit column is selected."})
    return I, U

def analyse(df, name, sample, mapping=None):
    if mapping is None: m, notes = detect(df)
    else: m, notes = {r: mapping.get(r) for r in ALIASES}, []
    d = prep(df, m); I, U = insights(d, m)
    num = df.select_dtypes(include="number")
    summ = json.loads(num.describe().T[["count", "mean", "std", "min", "50%", "max"]].round(2).to_json(orient="index")) if not num.empty else {}
    miss = df.isna().sum()
    cols = [{"name": c, "dtype": str(df[c].dtype), "missing": int(miss[c]), "missing_pct": round(100 * miss[c] / len(df), 1), "unique": int(df[c].nunique())} for c in df.columns]
    return {"name": name, "sample": sample, "rows": len(df), "cols": len(df.columns), "columns": cols, "mapping": m, "notes": notes,
            "kpis": kpis(df, d, m), "quality": quality(df, m), "charts": charts(d, m), "insights": I, "unavailable": U, "numeric_summary": summ}

def activate(df, name, sample):
    p = analyse(df, name, sample)   # raises before touching STATE, so a failed load keeps the old dataset
    STATE.update(df=df, name=name, sample=sample, analysis=p)
    return jsonify(p)

def need():
    if STATE["df"] is None: raise UserError("No dataset is loaded. Upload a file or try the sample dataset first.", 409)
    return STATE["df"], STATE["analysis"]["mapping"]


# ---------- Ask DataPilot (rule-based; NOT a language model) ----------

def answer_question(q, df, m):
    """Answer dataset questions using local, rule-based calculations."""
    ql = str(q).lower().strip()
    d = prep(df, m)
    R, P = m.get("revenue"), m.get("profit")

    def has(*patterns):
        return any(
            re.search(r"\b(?:" + pattern + r")\b", ql)
            for pattern in patterns
        )

    def A(text, basis):
        return {"answer": text, "basis": basis}

    def lack(what, role):
        return A(
            f"I can't answer because no {what} column is selected. "
            "Choose one in Settings.",
            f"Missing column role: {role}"
        )

    # Missing values
    if has("missing", "null", "blank", "empty"):
        missing = df.isna().sum()
        missing = missing[missing > 0].sort_values(ascending=False)

        if len(missing):
            details = ", ".join(
                f"{col} ({int(count):,})"
                for col, count in missing.items()
            )
            return A(
                f"Missing values were found in: {details}.",
                "Count of empty cells per column"
            )

        return A(
            "No missing values were found.",
            "Count of empty cells per column"
        )

    # Duplicate rows
    if has("duplicat"):
        count = int(df.duplicated().sum())
        return A(
            f"{count:,} duplicate rows were found."
            if count else "No duplicate rows were found.",
            "DataFrame.duplicated() across all columns"
        )

    # Dataset size
    if has("how many (rows|records)", "rows", "records", "row count"):
        return A(
            f"The dataset has {len(df):,} rows and "
            f"{len(df.columns):,} columns.",
            "DataFrame shape"
        )

    # Column names
    if has("column", "columns", "field", "fields"):
        return A(
            "Columns: " + ", ".join(map(str, df.columns)) + ".",
            "DataFrame column names"
        )

    # Monthly trends
    if has("month", "monthly", "trend", "over time", "changed"):
        g = monthly(d)

        if g is None:
            return A(
                "Monthly analysis requires a usable date column "
                "and a revenue column.",
                "Needs date and revenue roles"
            )

        g = g.dropna().tail(12)

        if g.empty:
            return A(
                "There is not enough valid date and revenue data "
                "to calculate a monthly trend.",
                "Monthly revenue grouped by calendar month"
            )

        details = "; ".join(
            f"{period}: {_n(value)}"
            for period, value in g.items()
        )

        return A(
            f"Monthly {R} for the most recent available months: "
            f"{details}.",
            f"Sum of {R} grouped by calendar month"
        )

    # Profit margin
    if has("margin"):
        if not (R and P):
            return lack("revenue and profit", "revenue/profit")

        valid = d.dropna(subset=["revenue", "profit"])
        revenue_total = valid["revenue"].sum()

        if revenue_total == 0:
            return A(
                "Profit margin cannot be calculated because "
                "total revenue is zero.",
                "Sum of profit divided by sum of revenue"
            )

        margin = 100 * valid["profit"].sum() / revenue_total

        return A(
            f"Profit margin is {margin:.2f}%.",
            "Total profit divided by total revenue for valid rows"
        )

    # Best or worst category
    if has("categor", "segment", "department"):
        if not m.get("category"):
            return lack("a category", "category")

        metric = "profit" if has("profit") else "revenue"
        role = P if metric == "profit" else R

        if not role:
            return lack(metric, metric)

        grouped = by(d, "category", metric)

        if grouped.empty:
            return A(
                "There is not enough valid category data to rank.",
                f"{metric.title()} grouped by category"
            )

        if has("worst", "lowest", "least", "bottom"):
            grouped = grouped.sort_values(ascending=True)
            label = "lowest"
        else:
            grouped = grouped.sort_values(ascending=False)
            label = "highest"

        ranking = ", ".join(
            f"{name} ({_n(value)})"
            for name, value in grouped.items()
        )

        return A(
            f"The category with the {label} {metric} is "
            f"'{grouped.index[0]}' ({_n(grouped.iloc[0])}). "
            f"Ranking: {ranking}.",
            f"Sum of {metric} grouped by category"
        )

    # Best or worst product
    if has("product", "products", "item", "items", "sku"):
        if not m.get("product"):
            return lack("a product", "product")

        if not R:
            return lack("revenue", "revenue")

        grouped = by(d, "product")

        if grouped.empty:
            return A(
                "There is not enough valid product data to rank.",
                "Revenue grouped by product"
            )

        if has("profit") and P:
            grouped = by(d, "product", "profit")
            metric = "profit"
        else:
            metric = "revenue"

        if has("worst", "lowest", "least", "bottom"):
            grouped = grouped.sort_values(ascending=True)
            label = "lowest"
        else:
            grouped = grouped.sort_values(ascending=False)
            label = "highest"

        ranking = ", ".join(
            f"{name} ({_n(value)})"
            for name, value in grouped.head(5).items()
        )

        return A(
            f"The product with the {label} {metric} is "
            f"'{grouped.index[0]}' ({_n(grouped.iloc[0])}). "
            f"Top ranking results: {ranking}.",
            f"Sum of {metric} grouped by product"
        )

    # Highest or lowest individual revenue/profit value
    if has("highest", "maximum", "max", "largest", "lowest",
           "minimum", "min", "smallest"):
        metric = "profit" if has("profit") else "revenue"
        role = P if metric == "profit" else R

        if not role:
            return lack(metric, metric)

        values = d[metric].dropna()

        if values.empty:
            return A(
                f"No valid {metric} values are available.",
                f"Valid values in {metric}"
            )

        if has("lowest", "minimum", "min", "smallest"):
            value = values.min()
            label = "Lowest"
        else:
            value = values.max()
            label = "Highest"

        return A(
            f"{label} {metric} value is {_n(value)}.",
            f"{label} value in the {metric} column"
        )

    # Total profit
    if has("profit"):
        if not P:
            return lack("profit", "profit")

        return A(
            f"Total profit is {_n(d['profit'].sum())}.",
            f"Sum of {P}"
        )

    # Average revenue
    if has("average", "mean", "typical"):
        if not R:
            return lack("revenue", "revenue")

        return A(
            f"Average {R} per record is {_n(d['revenue'].mean())}.",
            f"Mean of {R}"
        )

    # Total sales or revenue
    if has("sales", "revenue", "total", "turnover"):
        if not R:
            return lack("revenue", "revenue")

        return A(
            f"Total {R} is {_n(d['revenue'].sum())}.",
            f"Sum of {R}"
        )

    # Default response
    return A(
        "Try asking about total revenue, total profit, average "
        "revenue, highest or lowest values, profit margin, top "
        "or bottom products, category performance, monthly trends, "
        "row counts, duplicate rows, missing values, or column names.",
        "No matching question rule"
    )


# ---------- routes ----------
@app.get("/")
def index(): return render_template("index.html")

@app.get("/api/state")
def api_state(): return jsonify(STATE["analysis"] or {"name": None})

@app.post("/api/sample")
def api_sample():
    return activate(pd.read_csv(os.path.join(BASE, "data", "sample_sales.csv")), "Sample sales data (sample)", True)

@app.post("/api/upload")
def api_upload():
    f = request.files.get("file")
    if f is None or not f.filename: raise UserError("No file received. Choose a CSV or Excel file.", 400)
    return activate(load_frame(f.filename, f.read()), os.path.basename(f.filename), False)

@app.post("/api/mapping")
def api_mapping():
    df, _ = need(); req = (request.get_json(silent=True) or {}).get("mapping")
    if not isinstance(req, dict): raise UserError("Invalid request.", 400)
    new = {}
    for role in ALIASES:
        col = req.get(role) or None
        if col is not None:
            if col not in df.columns: raise UserError(f"Column '{col}' does not exist.", 400)
            share = usable(df[col], role)
            if share < 0.8: raise UserError(f"'{col}' can't be used as {role}: only {share*100:.0f}% of its values are valid {role} values.")
        new[role] = col
    p = analyse(df, STATE["name"], STATE["sample"], new); STATE["analysis"] = p
    return jsonify(p)

@app.post("/api/ask")
def api_ask():
    q = str((request.get_json(silent=True) or {}).get("question", "")).strip()
    if not q: raise UserError("Type a question first.", 400)
    if len(q) > 500: raise UserError("Questions are limited to 500 characters.", 400)
    df, m = need(); return jsonify(answer_question(q, df, m))

@app.get("/api/rows")
def api_rows():
    df, _ = need(); q = request.args.get("q", "").strip(); sort = request.args.get("sort", "")
    v = df
    if q: v = v[v.astype(str).apply(lambda s: s.str.contains(q, case=False, regex=False)).any(axis=1)]
    if sort in df.columns:
        asc = request.args.get("dir") != "desc"
        try: v = v.sort_values(sort, ascending=asc, na_position="last", kind="stable")
        except TypeError: v = v.loc[v[sort].astype(str).sort_values(ascending=asc, kind="stable").index]
    size = 10; pages = max(1, -(-len(v) // size)); page = min(max(1, request.args.get("page", 1, type=int)), pages)
    p = v.iloc[(page - 1) * size: page * size].copy()
    for c in p.columns:
        if pd.api.types.is_datetime64_any_dtype(p[c]): p[c] = p[c].dt.strftime("%Y-%m-%d")
    return jsonify({"columns": list(df.columns), "rows": json.loads(p.to_json(orient="values")), "index": [int(i) + 1 for i in p.index],
                    "total": len(v), "page": page, "pages": pages, "size": size})

@app.errorhandler(UserError)
def on_user_error(e): return jsonify(error=e.msg), e.code

@app.errorhandler(Exception)
def on_error(e):
    if isinstance(e, HTTPException):
        return jsonify(error="The file is too large. The maximum upload size is 16 MB." if e.code == 413 else e.description), e.code
    app.logger.exception("Unhandled error")
    return jsonify(error="Something went wrong while analysing the data."), 500

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
