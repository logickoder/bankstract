# Reconciliation

The invariant is load-bearing. If a parser change breaks reconciliation on any fixture, the parser is wrong, not the invariant. Never weaken `reconcile.py` to make tests pass.

- **Row-wise:** `prev.balance ± debit/credit == curr.balance`. Runs when every row has a balance and the parser didn't opt out.
- **Totals:** parsed credit and debit sums equal the header totals. Runs when the parser read them.

`reconcile_result(result)` is the entry point. It runs every check with evidence and returns a copy with `.reconciliation` set (`passed`, `not_available`, `disabled` per check). It raises `ReconciliationError` when no check can run, and when a balance column is blank on some rows but not others. `convert()` and the CLI call it. `parse()` never does.

`row_wise_reconcilable=False` is only for balances that are present but don't chain (opay OWealth moves). An opted-out parser MUST supply header totals.
