# Parsing lineup PDF data

This repository contains a helper to transform the two-page lineup PDF into a
single pandas DataFrame. Use `parse_lineup_pdf` from `parse_lineups.py` to read
`lineup-analysis_D1_QAT_LBN_20251127.pdf` (or similar exports) and normalize the
statistics for both teams.

## Usage

```python
from parse_lineups import parse_lineup_pdf

pdf_path = "lineup-analysis_D1_QAT_LBN_20251127.pdf"
df = parse_lineup_pdf(pdf_path)
print(df.head())
```

The parser will infer team names from the filename when possible, split the
score and field-goal values, and return a DataFrame with these columns:

- `Team`, `Opponent`
- `Lineup`, `Min`
- `Team Score`, `Opponent Score`
- `FGA`, `FGM`
- `OR`, `DR`, `AS`, `TO`, `ST`

Install dependencies with:

```bash
pip install -r requirements.txt
```
