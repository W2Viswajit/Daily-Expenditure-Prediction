# Verification

Tested using fictional sample transactions only. The release itself starts empty.

- Imported the 119-row sample as CSV and XLSX; re-import skipped duplicate IDs.
- Reviewed all four synthetic merchants, saved categories, and verified persistence after browser reload and server restart.
- Confirmed 90 days, trained both regressors, and forecast seven days through 2026-11-02.
- Checked every day's category allocations sum exactly to its forecast total, to the paise.
- Tested soft deletion and restore, permanent-delete confirmation validation, stale-model blocking after edits, and persistent forecast history through isolated backend tests.
- Browser-tested Excel upload, dropdown category review, bulk merchant review, day confirmation, UI training and prediction.
- Browser-tested the default incoming-money budget and a manual override. The fictional seven-day forecast was expenses ₹1,484.25 and receipts ₹2,091.78 (Within budget). An override of ₹1,000 changed it to Exceeded.
- Inspected mobile (390×844) and desktop (1280×900) layouts; mobile document width did not overflow. Narrow tables scroll within their container. Reduced-motion CSS disables the reveal animation.
- Executed all notebook code cells on the synthetic dataset; distributed notebook outputs remain empty.
- Scanned public source for personal names and the prior personal exclusions; verified that no database or trained model is bundled.

The regular synthetic pattern is for functional testing. Its high test scores do not establish accuracy for real transaction histories. Multi-day forecast accuracy has not been validated by the one-day holdout scores.
