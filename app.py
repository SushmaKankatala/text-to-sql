"""Text-to-SQL backend (Gemini + Northwind real e-commerce data)."""
import os, json, sqlite3, re
from flask import Flask, request, jsonify, send_from_directory
from google import genai
from google.genai import types

app = Flask(__name__, static_folder="static")
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
DB = os.path.join(os.path.dirname(__file__), "northwind.db")
MODEL = "gemini-2.5-flash"

SCHEMA = """Tables (SQLite) — Northwind e-commerce database:
Categories(CategoryID, CategoryName, Description)
Customers(CustomerID, CompanyName, ContactName, City, Country)
Suppliers(SupplierID, CompanyName, Country)
Products(ProductID, ProductName, SupplierID, CategoryID, UnitPrice, UnitsInStock, Discontinued)
Orders(OrderID, CustomerID, EmployeeID, OrderDate, ShippedDate, ShipVia, Freight, ShipCity, ShipCountry)
"Order Details"(OrderID, ProductID, UnitPrice, Quantity, Discount)
Employees(EmployeeID, FirstName, LastName, Title, Country)
Shippers(ShipperID, CompanyName)

IMPORTANT: the line-items table is named "Order Details" (with a space) — always wrap it in double quotes.
Revenue/sales = SUM("Order Details".UnitPrice * "Order Details".Quantity * (1 - "Order Details".Discount)).
Join: Orders.OrderID = "Order Details".OrderID ; "Order Details".ProductID = Products.ProductID ; Products.CategoryID = Categories.CategoryID.
For monthly trends use strftime('%Y-%m', Orders.OrderDate); for yearly use strftime('%Y', Orders.OrderDate). Data spans 2012-2023."""

SYSTEM = f"""You are a SQL analyst. Convert the user's question into ONE valid SQLite SELECT query.
{SCHEMA}
Respond with ONLY a JSON object shaped like:
{{"sql":"<single SELECT query>","explanation":"<one plain-English sentence>","chart":{{"type":"bar|hbar|line|area|pie|none","labelCol":"<col>","valueCol":"<col>"}}}}
Pick the chart type that best fits the answer:
- "line" or "area": a metric changing over time (monthly/yearly trends).
- "hbar" (horizontal bar): rankings or top-N, especially with long labels like product names or countries.
- "bar" (vertical): comparing a handful of categories.
- "pie": share / proportion of a small number of parts.
- "none": a single value or something not chartable.
Always alias aggregates with clear names and round money to 2 decimals. Limit rankings to a sensible top-N (e.g. 10)."""

BLOCKED = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|PRAGMA)\b", re.I)

def run_sql(sql):
    if BLOCKED.search(sql) or ";" in sql.strip().rstrip(";"):
        raise ValueError("Only single read-only SELECT queries are allowed.")
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
    finally:
        con.close()
    return cols, [list(r) for r in rows]

@app.route("/")
def home():
    return send_from_directory("static", "index.html")

@app.route("/api/ask", methods=["POST"])
def ask():
    question = (request.json or {}).get("question", "").strip()
    if not question:
        return jsonify({"error": "Empty question"}), 400
    try:
        resp = client.models.generate_content(
            model=MODEL, contents=question,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM, temperature=0,
                response_mime_type="application/json"),
        )
        plan = json.loads(resp.text)
        cols, rows = run_sql(plan["sql"])
        return jsonify({**plan, "columns": cols, "rows": rows})
    except Exception as e:
        return jsonify({"error": str(e)}), 200

if __name__ == "__main__":
    app.run(debug=True, port=5000)
