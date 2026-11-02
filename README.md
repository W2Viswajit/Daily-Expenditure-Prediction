# Personal Expense Tracker

A local, single-user PhonePe tracker with a blue-and-gold Art Deco interface. No personal records, trained models or credentials are bundled. Start with your own statement or the **entirely synthetic** sample.

## Run

Use Python 3.11–3.13. From this folder in PowerShell (the command below selects Python 3.13):

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python app.py
```

Open http://127.0.0.1:8502. Keep the terminal running. Closing and reopening the browser does not erase transactions, reviews, completed days, models or prediction history. Restart the same command after restarting the computer. The notebook is optional; the website can import, review, train and predict on its own.

## Try the sample

1. Upload `sample_phonepe.csv` (or the equivalent `sample_phonepe.xlsx`, not both).
2. Review each merchant. Select **Apply to all transactions with this exact description and direction**, then save:
   - DEMO Cafe → food
   - DEMO Allowance → income
   - DEMO Clothing → fashion
   - DEMO Recharge → bills
3. Confirm **2026-07-29 through 2026-10-26** complete. The file covers all 90 days; gaps in categories are intentional.
4. Train / refresh models. Select **2026-11-02** to forecast seven days, or **2026-11-03** for an eight-day extended forecast. The maximum horizon is 14 days after confirmed history.
5. View the category split and Budget classification page. The synthetic pattern is deliberately regular for testing; its performance is not evidence of real-world accuracy.

## Workflow

Upload → review → confirm coverage → train → predict. Category choices include fashion, online shopping and offline shopping; add your own categories as needed. Manual entries use date, amount, description, direction and category. Category reviews and imports persist in SQLite. Duplicate statement IDs are skipped; conflicting duplicates fail without partial imports. Review and exclude refunds, own-account transfers or borrowing if they should not fund the spending budget. All unknown categories must be reviewed.

Confirm days only when all activity is recorded. Confirmed gaps become zero-spend/zero-credit days. Unconfirmed gaps stop training history; they are never silently treated as zero. Adding, deleting or restoring a transaction reopens its day. Review changes mark models stale. Retrain in the UI after edits. Training requires 70 consecutive complete days and six included credit dates.

Trash supports restore. Permanent deletion requires typing DELETE, removes the tracker record, and retains only an ID tombstone so the same ID cannot return on re-upload. The original file on your computer is unchanged. Prediction history can be deleted separately; history is a snapshot, not actual spending. Retrain from the history section when needed.

## What the predictions mean

Two regressors independently estimate daily expenses and included incoming credits. Candidates are historical mean, Ridge, Extra Trees and Gradient Boosting. Expanding chronological validation selects each model. The latest 20% is reserved for one-day holdout evaluation, then deployment refits on all completed history. Lagged values, rolling means and calendar features avoid same-day target leakage. Forecasts beyond one day recursively use earlier predictions; the one-day test metrics do not validate multi-day accuracy. R² may be negative.

The seven-day budget window ends on the chosen forecast date. Its estimated budget is included recorded credits plus forecast incoming money within that **same** window. With a seven-day horizon it uses seven predicted credit amounts. A manual budget override is optional and saved in this browser. Estimated expenses greater than the budget are **Exceeded / Critical**; otherwise **Within budget / Normal**. This is a deterministic comparison, not a trained classifier. These labels describe expected totals, not whether future money has already been spent. Credits do not represent bank balance, savings, disposable income or guaranteed income.

Category amounts distribute the selected day's total using the last 28 completed days' debit proportions. Rounded amounts sum exactly to the total. They are allocation estimates, not separately trained category forecasts; new categories with no history receive no allocation until spending is recorded.

## Notebook and reporting

`Expense_Analysis.ipynb` uses your locally saved reviewed data for data inspection, plots and model comparison. Run it after importing, categorizing and confirming coverage. Do not run notebook training while UI training is running. `STAGES.md` explains the implementation and limits. Survey/questionnaire/Google Form collection is not claimed: this project uses transaction statements.

## Share source safely

The `.gitignore` excludes runtime data, models, results, environments and secrets. Before publishing, inspect `git status` and the files to be committed; never force-add these excluded folders. Do not commit notebook outputs containing your data. The sample alone is fictional and shareable. This server binds only to localhost and is designed for one trusted user. Internet hosting requires authentication, per-user data isolation, HTTPS and deployment-specific storage work.

All records remain local; this project has no Jev/TypeSafe or other external transaction-classification integration.

## Launch from an existing terminal

Once dependencies are installed, run `./start.cmd` in this folder. It selects the project environment even if your global `python` points to another version. Alternatively run `.\.venv\Scripts\python.exe app.py`. No PowerShell activation or execution-policy change is needed. In VS Code, use **Python: Select Interpreter** and select `.venv\Scripts\python.exe`; use the same environment as the notebook kernel.

If training reports too few complete days, confirm every fully recorded day from the start of history in section 03. A single unconfirmed date stops the consecutive history. Do not confirm missing real records as zero. Extended forecasts estimate intervening days recursively; they never add those estimates as transactions.
