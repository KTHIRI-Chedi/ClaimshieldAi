# Real invoices (local only)

Put real garage invoices (PDF, JPG, PNG) here to test the Invoice Parser Agent. Everything in this folder except this README is **git-ignored**: real invoices contain customer data and must never be committed.

Prefer anonymized invoices (customer name and plate hidden) and do not send real customer data to services on a free tier.

```bash
python scripts/run_invoice_agent.py data/invoices/real/facture1.pdf data/invoices/real/facture2.jpg
```

For each file, check by hand: the lines (`part` / `labor` / `other`), the total, and above all that a correct invoice does **not** come out as `arithmetic_mismatch` (false fraud). Report any error with the anonymized file.
