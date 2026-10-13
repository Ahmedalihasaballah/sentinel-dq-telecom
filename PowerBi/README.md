# DataSentinel Power BI report

A Power BI project (PBIP) on the 12 Gold marts in `data_sentinel.gold`. The report and model are
stored as text files, so they diff and merge in Git like code.

## Open it

1. Pull the repo and open `PowerBi/model/DataSentinel.pbip` in Power BI Desktop (2.13x or later).
2. Click **Refresh**. When asked, sign in to Databricks with a **personal access token**
   (server `dbc-21b8c56c-c07d.cloud.databricks.com`, your SQL warehouse HTTP path).
   The token stays on your machine; it is never written to these files.
3. The report opens on **Network & App**. Click **☰** on the left strip to open the page menu and
   **✕** to close it. In Power BI Desktop, hold **Ctrl** while clicking; in the published report a
   plain click works. The menu is driven by the `… : menu open / menu closed` bookmarks.

Local caches (`.pbi/cache.abf`, `.pbi/localSettings.json`) are ignored by Git, so the first refresh
on a new machine loads the data from Databricks.

## Pages

| Page | Question it answers |
|---|---|
| Overview | Is today's data healthy, and what needs attention first? |
| Data Quality | Which datasets and rules fail, is it improving, how many rows wait in quarantine? |
| Revenue Assurance | How many EUR leak between systems, where, and which cases to investigate? |
| Incidents | Who owns each incident, how late is it, does the team meet its deadlines? |
| Customer 360 | Who has paid, who owes money, which customers have problems? |
| Network & App | Where do calls drop, how does the app behave, what does partner traffic cost? |

## Business targets

KPI cards show a status pill (✓ on target, ! below, ✕ critical). The thresholds are measures in
`_Measures`, so they can be changed in one place: `Target DQ Pass` (98%), `Target Drop Rate` (2%),
`Target SLA Compliance` (95%), `Target Collection` (95%), `Limit Crash Share` (2%).

## Regenerate the design

The files in `model/` are the finished report; you only need the scripts to rebuild or change the design.

```bash
# Power BI Desktop must be closed
python PowerBi/tools/build_model.py    # measures, Attention table, ageing columns, theme
python PowerBi/tools/build_report.py   # every report page
```

Both scripts are idempotent and use only the Python standard library. `build_report.py` rewrites
all page folders, so make layout changes in the script, not by hand in Desktop, or they will be lost
on the next run.
