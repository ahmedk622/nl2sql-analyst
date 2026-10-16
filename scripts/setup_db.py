"""Create the database, tables, synthetic data and the READ-ONLY app user.

Usage:  python scripts/setup_db.py            # (re)build everything
        python scripts/setup_db.py --if-empty # skip if data already exists (used by Docker)
"""
import argparse
import os
import random
import sys
from datetime import date, timedelta
from pathlib import Path

import pymysql
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

HOST = os.getenv("DB_HOST", "127.0.0.1")
PORT = int(os.getenv("DB_PORT", "3306"))
DB = os.getenv("DB_NAME", "analytics_demo")
ADMIN_USER = os.getenv("DB_ADMIN_USER", "root")
ADMIN_PW = os.getenv("DB_ADMIN_PASSWORD", "")
APP_USER = os.getenv("DB_USER", "analyst_ro")
APP_PW = os.getenv("DB_PASSWORD", "")

COUNTRIES = {
    "India": (40, ["Mumbai", "Delhi", "Bengaluru", "Pune", "Hyderabad"]),
    "UAE": (25, ["Dubai", "Abu Dhabi", "Sharjah"]),
    "USA": (15, ["New York", "Austin", "Seattle"]),
    "UK": (12, ["London", "Manchester"]),
    "Singapore": (8, ["Singapore"]),
}
FIRST = ["Aarav", "Sara", "Omar", "Priya", "Liam", "Fatima", "Rohan", "Emma", "Yusuf", "Ananya", "Noah", "Zara",
         "Kabir", "Mia", "Hamza", "Isha", "Ethan", "Layla", "Arjun", "Chloe", "Imran", "Diya", "Lucas", "Meera"]
LAST = ["Khan", "Sharma", "Patel", "Smith", "Ali", "Nair", "Brown", "Iyer", "Hussain", "Verma", "Taylor", "Shaikh",
        "Reddy", "Wilson", "Ahmed", "Gupta", "Davies", "Joshi", "Lee", "Mehta"]
CATALOG = {
    "Electronics": [("Wireless Earbuds", 59), ("Bluetooth Speaker", 45), ("Smart Watch", 120), ("Power Bank", 28),
                    ("USB-C Hub", 35), ("Webcam HD", 49), ("Mechanical Keyboard", 79), ("Gaming Mouse", 39)],
    "Home & Kitchen": [("Air Fryer", 110), ("Electric Kettle", 32), ("Blender", 55), ("Cookware Set", 130),
                       ("Vacuum Flask", 22), ("Knife Set", 65), ("Desk Lamp", 30), ("Storage Boxes", 25)],
    "Fitness": [("Yoga Mat", 25), ("Dumbbell Set", 90), ("Resistance Bands", 18), ("Running Shoes", 85),
                ("Fitness Tracker", 70), ("Jump Rope", 12), ("Foam Roller", 24), ("Gym Bag", 38)],
    "Stationery": [("Notebook Pack", 9), ("Gel Pens", 7), ("Desk Organizer", 20), ("Planner 2025", 15),
                   ("Highlighters", 6), ("Sticky Notes", 5), ("Whiteboard", 40), ("Sketch Pad", 12)],
    "Fashion": [("Denim Jacket", 75), ("Cotton T-Shirt", 18), ("Sneakers", 68), ("Leather Wallet", 35),
                ("Sunglasses", 45), ("Backpack", 55), ("Wrist Watch", 95), ("Scarf", 20)],
}
STATUS = (["completed"] * 80 + ["cancelled"] * 8 + ["returned"] * 7 + ["pending"] * 5)
CHANNEL = (["web"] * 40 + ["mobile_app"] * 30 + ["marketplace"] * 20 + ["store"] * 10)
SEGMENT = (["Consumer"] * 60 + ["SMB"] * 30 + ["Enterprise"] * 10)
N_CUSTOMERS, N_ORDERS = 300, 3000
DATA_START, DATA_END = date(2024, 1, 1), date(2025, 12, 31)


def rand_date(lo: date, hi: date) -> date:
    return lo + timedelta(days=random.randint(0, (hi - lo).days))


def generate():
    random.seed(42)
    country_pool = [c for c, (w, _) in COUNTRIES.items() for _ in range(w)]
    customers = []
    for cid in range(1, N_CUSTOMERS + 1):
        country = random.choice(country_pool)
        f, l = random.choice(FIRST), random.choice(LAST)
        customers.append((cid, f"{f} {l}", f"{f.lower()}.{l.lower()}{cid}@example.com",
                          random.choice(COUNTRIES[country][1]), country, random.choice(SEGMENT),
                          rand_date(date(2023, 6, 1), date(2025, 11, 30))))
    products, pid = [], 0
    for cat, items in CATALOG.items():
        for name, price in items:
            pid += 1
            products.append((pid, name, cat, price, round(price * random.uniform(0.45, 0.75), 2)))
    # skewed demand: a minority of customers order a lot; ~12% never order
    buyers = customers[: int(N_CUSTOMERS * 0.88)]
    weights = [random.paretovariate(1.6) for _ in buyers]
    orders, items, iid = [], [], 0
    for oid in range(1, N_ORDERS + 1):
        c = random.choices(buyers, weights)[0]
        odate = rand_date(max(c[6], DATA_START), DATA_END)
        orders.append((oid, c[0], odate, random.choice(STATUS), random.choice(CHANNEL)))
        for p in random.sample(products, random.randint(1, 5)):
            iid += 1
            items.append((iid, oid, p[0], random.randint(1, 4),
                          round(float(p[3]) * random.uniform(0.95, 1.05), 2),
                          random.choice([0, 0, 0, 5, 10, 15, 20])))
    return customers, products, orders, items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--if-empty", action="store_true")
    args = ap.parse_args()

    conn = pymysql.connect(host=HOST, port=PORT, user=ADMIN_USER, password=ADMIN_PW, autocommit=True)
    cur = conn.cursor()
    cur.execute(f"CREATE DATABASE IF NOT EXISTS `{DB}`")
    cur.execute(f"USE `{DB}`")

    if args.if_empty:
        cur.execute("SHOW TABLES LIKE 'orders'")
        if cur.fetchone():
            cur.execute("SELECT COUNT(*) FROM orders")
            if cur.fetchone()[0] > 0:
                print("Data already present - skipping seed.")
                _grant(cur)
                return

    for stmt in (ROOT / "sql" / "schema.sql").read_text().split(";"):
        if stmt.strip():
            cur.execute(stmt)
    customers, products, orders, items = generate()
    cur.executemany("INSERT INTO customers VALUES (%s,%s,%s,%s,%s,%s,%s)", customers)
    cur.executemany("INSERT INTO products VALUES (%s,%s,%s,%s,%s)", products)
    cur.executemany("INSERT INTO orders VALUES (%s,%s,%s,%s,%s)", orders)
    cur.executemany("INSERT INTO order_items VALUES (%s,%s,%s,%s,%s,%s)", items)
    print(f"Seeded {len(customers)} customers, {len(products)} products, "
          f"{len(orders)} orders, {len(items)} order items.")
    _grant(cur)


def _grant(cur):
    cur.execute(f"CREATE USER IF NOT EXISTS %s@'%%' IDENTIFIED BY %s", (APP_USER, APP_PW))
    cur.execute(f"ALTER USER %s@'%%' IDENTIFIED BY %s", (APP_USER, APP_PW))
    cur.execute(f"GRANT SELECT ON `{DB}`.* TO %s@'%%'", (APP_USER,))
    cur.execute("FLUSH PRIVILEGES")
    print(f"Read-only user '{APP_USER}' ready (SELECT only on {DB}).")


if __name__ == "__main__":
    sys.exit(main())
