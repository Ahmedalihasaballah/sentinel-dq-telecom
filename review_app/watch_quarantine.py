"""Live view of the quarantine tables in the terminal (refreshes like a Databricks result grid).

    .venv\\Scripts\\python review_app\\watch_quarantine.py                       all datasets, every 20 s
    .venv\\Scripts\\python review_app\\watch_quarantine.py --dataset crm_customers --every 10

Shows the status counts per dataset and the rows of one dataset; every row whose status changed since the
previous refresh is highlighted (e.g. REJECTED -> FIXED_PENDING_REVALIDATION -> REVALIDATED_OK), and rows that
left the quarantine (they now pass the gate and are in Silver) are listed. Ctrl+C stops it.
Note: each refresh is a query on the SQL warehouse, which keeps it running while you watch.
"""
import argparse
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(HERE.parent / ".env")
load_dotenv(HERE.parent / "airflow" / ".env")

import db  # noqa: E402
from logic import load_contracts, safe_name  # noqa: E402

os.system("")  # enables ANSI colours in the Windows terminal
RESET, BOLD, DIM = "\x1b[0m", "\x1b[1m", "\x1b[2m"
COLOR = {"REJECTED": "\x1b[31m", "PENDING_FIX": "\x1b[33m", "FIXED_PENDING_REVALIDATION": "\x1b[36m",
         "REVALIDATED_OK": "\x1b[32m", "CHANGED": "\x1b[45;97m", "LEFT": "\x1b[42;30m"}
ANSI = re.compile(r"\[[0-9;]*m")
# columns listed per dataset (the ones the fixes and rules are about); others: the first four contract columns
SHOW = {"crm_customers": ["customer_id", "msisdn", "email", "status"], "billing_accounts": ["account_id", "msisdn", "account_ref", "status"],
        "network_cdr": ["cdr_id", "msisdn", "duration_sec", "cell_id"], "billing_payments": ["payment_id", "invoice_id", "amount", "method"]}
STATUSES = ["REJECTED", "PENDING_FIX", "FIXED_PENDING_REVALIDATION", "REVALIDATED_OK"]


def paint(text, status):
    return f"{COLOR.get(status, '')}{text}{RESET}"


def grid(headers, rows, styles=None):
    """Box-drawn table like the Databricks result grid. styles[i] = ANSI prefix for row i (or None)."""
    cells = [[("" if v is None else str(v)) for v in r] for r in rows]
    vis = lambda t: len(ANSI.sub("", t))  # noqa: E731  visible length, colour codes excluded
    pad = lambda t, w: t + " " * (w - vis(t))  # noqa: E731
    widths = [max([len(h)] + [vis(r[i]) for r in cells]) for i, h in enumerate(headers)]
    line = lambda l, m, r: l + m.join("─" * (w + 2) for w in widths) + r  # noqa: E731
    out = [line("┌", "┬", "┐"), "│" + "│".join(f" {BOLD}{h.ljust(w)}{RESET} " for h, w in zip(headers, widths)) + "│",
           line("├", "┼", "┤")]
    for i, r in enumerate(cells):
        pre = (styles or [None] * len(cells))[i] or ""
        out.append("│" + "│".join(f" {pre}{pad(c, w)}{RESET if pre else ''} " for c, w in zip(r, widths)) + "│")
    out.append(line("└", "┴", "┘"))
    return "\n".join(out)


def status_counts(conn, datasets):
    parts = [f"SELECT '{safe_name(d)}' AS ds, _quarantine_status AS st, count(*) AS n FROM {db.quarantine_table(d)} GROUP BY 2"
             for d in datasets if db.table_exists(conn, d)]
    out = {}
    for r in db._rows(conn, " UNION ALL ".join(parts)) if parts else []:
        out.setdefault(r["ds"], {})[r["st"]] = r["n"]
    return out


def snapshot(conn, dataset, columns):
    """All rows of one quarantine table: _row_id -> row (key columns, status, reason, fixed value, attempts)."""
    show = [c for c in SHOW.get(dataset, []) if c in columns] or columns[:4]
    cols = ", ".join(f"CAST({safe_name(c)} AS STRING) AS {c}" for c in show)
    rows = db._rows(conn, f"""SELECT _row_id, {cols}, _quarantine_status AS q_status, _failure_reasons AS reason,
                              CAST(_fixed AS STRING) AS fixed, _attempts AS attempts
                              FROM {db.quarantine_table(dataset)}""")
    return {r["_row_id"]: r for r in rows}, show


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="crm_customers", help="dataset whose rows are listed")
    ap.add_argument("--every", type=int, default=20, help="seconds between refreshes")
    ap.add_argument("--rows", type=int, default=15, help="max rows listed")
    ap.add_argument("--once", action="store_true", help="one refresh, then exit")
    args = ap.parse_args()

    contracts = load_contracts(HERE.parent / "contract")
    if args.dataset not in contracts:
        sys.exit(f"unknown dataset {args.dataset}; choose from {', '.join(sorted(contracts))}")
    conn = db.connect()
    prev_counts, prev_rows, history = {}, None, []
    try:
        while True:
            counts = status_counts(conn, sorted(contracts))
            rows, show = snapshot(conn, args.dataset, contracts[args.dataset])
            now = datetime.now().strftime("%H:%M:%S")

            if prev_rows is not None:  # what changed since the last refresh
                for rid, r in rows.items():
                    old = prev_rows.get(rid)
                    if old is None:
                        history.append((now, rid, "(new)", r["q_status"]))
                    elif old["q_status"] != r["q_status"]:
                        history.append((now, rid, old["q_status"], r["q_status"]))
                    elif old["fixed"] != r["fixed"]:  # edited again in the review app, same status
                        history.append((now, rid, r["q_status"], r["q_status"] + " (value edited)"))
                for rid in prev_rows.keys() - rows.keys():
                    history.append((now, rid, prev_rows[rid]["q_status"], "LEFT → Silver"))
            changed_now = {h[1] for h in history if h[0] == now}

            print("\x1b[2J\x1b[H", end="")  # clear screen, cursor home
            print(f"{BOLD}DataSentinel · quarantine live view{RESET}   {DIM}refreshed {now}, every {args.every}s · Ctrl+C to stop{RESET}\n")

            head = ["dataset"] + STATUSES + ["total", "Δ since last"]
            body = []
            for ds in sorted(counts):
                c = counts[ds]
                total, before = sum(c.values()), sum(prev_counts.get(ds, {}).values()) if prev_counts else None
                delta = "" if before is None or before == total else f"{total - before:+,}"
                body.append([ds] + [f"{c.get(s, 0):,}" for s in STATUSES] + [f"{total:,}", delta])
            print(grid(head, body, [COLOR["CHANGED"] if b[-1] else None for b in body]))

            print(f"\n{BOLD}{args.dataset}{RESET} rows ({len(rows):,} in quarantine; changed rows first)")
            ordered = sorted(rows.values(), key=lambda r: (r["_row_id"] not in changed_now, r["q_status"], str(r[show[0]])))
            listing = [[r[c] for c in show] + [paint(r["q_status"], r["q_status"]), (r["reason"] or "")[:45],
                        (r["fixed"] or "")[:40], r["attempts"]] for r in ordered[: args.rows]]
            print(grid(show + ["quarantine status", "reason", "fixed (_fixed)", "tries"], listing,
                       [COLOR["CHANGED"] if r["_row_id"] in changed_now else None for r in ordered[: args.rows]]))

            print(f"\n{BOLD}Status changes{RESET} (latest 12)")
            if history:
                print(grid(["time", "row", "from", "to"],
                           [[t, rid[-24:], paint(a, a), paint(b, "LEFT" if b.startswith("LEFT") else b)] for t, rid, a, b in history[-12:]]))
            else:
                print(f"{DIM}  none yet: edit a row in the review app or run the pipeline, then watch it change here{RESET}")

            prev_counts, prev_rows = counts, rows
            if args.once:
                break
            time.sleep(args.every)
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
