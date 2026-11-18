"""Synthetic borrower data: one scenario file per borrower, rendered into documents.

    uv run python ../data/synthetic/generate.py        (from backend/)

Every figure lives in ``scenarios/<borrower>.json``. The generator reads only that
file, so a number such as 2,033.61 is identical in every document it appears in.
All people, employers and accounts are invented.
"""
