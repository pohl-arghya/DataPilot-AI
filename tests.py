"""Run:  python tests.py   (uses Flask's test client; no server needed)"""
import io, pandas as pd
from app import app, STATE
c = app.test_client(); n = 0
def check(name, cond):
    global n; n += 1; print(("PASS " if cond else "FAIL ") + name)
    if not cond: raise SystemExit(1)
def up(name, data): return c.post("/api/upload", data={"file": (io.BytesIO(data), name)}, content_type="multipart/form-data")
def ask(q): return c.post("/api/ask", json={"question": q}).get_json()

check("homepage loads", c.get("/").status_code == 200)
check("ask without dataset -> 409", c.post("/api/ask", json={"question": "total sales"}).status_code == 409)
r = c.post("/api/sample"); s = r.get_json(); raw = pd.read_csv("data/sample_sales.csv")
check("sample loads", r.status_code == 200 and s["rows"] == len(raw))
kv = {k["key"]: k["value"] for k in s["kpis"]}
check("sample revenue matches pandas", abs(kv["revenue"] - raw.Sales.sum()) < 0.01)
check("sample profit matches pandas", abs(kv["profit"] - raw.Profit.sum()) < 0.01)
both = raw.dropna(subset=["Sales", "Profit"]); check("sample margin matches", abs(kv["margin"] - both.Profit.sum() / both.Sales.sum() * 100) < 0.01)
check("sample missing cells", s["quality"]["missing_cells"] == int(raw.isna().sum().sum()))
check("sample duplicates", s["quality"]["duplicate_rows"] == int(raw.duplicated().sum()))
check("all 5 charts available", all(v["available"] for v in s["charts"].values()))
top = raw.groupby("Product").Sales.sum().idxmax(); check("ask top product", top in ask("Which product generated the most revenue?")["answer"])
check("ask total sales", f"{raw.Sales.sum():,.0f}" in ask("What are my total sales?")["answer"])

csv = b"Date,Product,Category,Sales,Profit,Qty\n2024-01-05,A,X,100,20,1\n2024-01-20,B,Y,200,50,2\n2024-02-10,A,X,150,30,1\n2024-02-10,A,X,150,30,1\n2024-03-01,B,Y,,40,3\n"
r = up("t.csv", csv); a = r.get_json()
check("csv upload ok", r.status_code == 200 and a["name"] == "t.csv")
kv = {k["key"]: k["value"] for k in a["kpis"]}
check("csv revenue=600", kv["revenue"] == 600 and kv["profit"] == 170)
check("csv margin=130/600", abs(kv["margin"] - 130 / 600 * 100) < 1e-9)
check("csv missing=1, duplicates=1", a["quality"]["missing_cells"] == 1 and a["quality"]["duplicate_rows"] == 1)
check("quantity alias 'Qty' detected", a["mapping"]["quantity"] == "Qty")
check("charts changed after new upload", a["charts"]["category"]["labels"] != s["charts"]["category"]["labels"])
check("ask uses new dataset", "600" in ask("total sales")["answer"] and "1 duplicate" in ask("duplicate rows")["answer"].replace("1 duplicate rows are", "1 duplicate"))

buf = io.BytesIO(); pd.read_csv(io.BytesIO(csv)).to_excel(buf, index=False)
r = up("t.xlsx", buf.getvalue()); check("xlsx upload ok", r.status_code == 200 and r.get_json()["rows"] == 5)
check(".txt rejected 415", up("x.txt", b"hello").status_code == 415)
check("empty file 422", up("e.csv", b"").status_code == 422)
check("header-only csv 422", up("h.csv", b"a,b,c\n").status_code == 422)
check("corrupt xlsx 422", up("bad.xlsx", b"not a real workbook").status_code == 422)
check("no file 400", c.post("/api/upload", data={}, content_type="multipart/form-data").status_code == 400)
check("failed upload keeps previous dataset", STATE["name"] == "t.xlsx")
check("oversize rejected 413", up("big.csv", b"a,b\n" + b"1,2\n" * 5_000_000).status_code == 413)

up("w.csv", b"Region,Total,Notes\nN,10,a\nS,20,b\n")
w = c.post("/api/sample") and up("w.csv", b"Region,Total,Notes\nN,10,a\nS,20,b\n").get_json()
check("'Total' not auto-used as revenue", w["mapping"]["revenue"] is None and any("revenue" in x for x in w["kpis"][0]["note"].lower().split()))
m = c.post("/api/mapping", json={"mapping": {"revenue": "Total"}}); check("manual mapping works", m.status_code == 200 and m.get_json()["kpis"][0]["value"] == 30)
check("invalid mapping rejected", c.post("/api/mapping", json={"mapping": {"revenue": "Notes"}}).status_code == 422)
c.post("/api/sample")
r = c.get("/api/rows?q=Desk&sort=Sales&dir=desc&page=1").get_json()
check("rows search+sort", r["total"] > 0 and all("desk" in " ".join(map(str, x)).lower() for x in r["rows"]) and r["rows"][0][3] >= r["rows"][-1][3])
check("rows paging", c.get("/api/rows?page=2").get_json()["page"] == 2)
print(f"\n{n} checks passed")
