# Markdown Table Readability

## Rule: Evaluate Every Table for Readability

Before generating or editing ANY markdown table, Cascade MUST evaluate
whether the table will render readably. Too many super-narrow, cramped
columns make documents unreadable.

## When to Switch to HTML Tables

- **4+ columns** where most cells contain short values
- **Extreme width imbalance** — any column > 60 characters alongside
  columns < 10 characters
- **Many rows (>15)** where column alignment is critical for scanning
- **Nested formatting** inside cells (bold + links + code) that gets
  squeezed into unreadable widths

## When Markdown Tables Are Fine

- 2–3 columns with balanced content widths
- Simple key-value style tables
- All cells have similar content length

## Decision Checklist

1. Count columns and estimate typical cell content width
2. If any column will render < 8 characters wide → **use HTML**
3. If mixed short/long columns cause extreme imbalance → **use HTML**
4. Use `<table>` with explicit widths for control

## HTML Table Template

```html
<table>
<tr><th style="width:20%">Column A</th><th style="width:30%">Column B</th><th style="width:50%">Column C</th></tr>
<tr><td>value</td><td>value</td><td>longer value here</td></tr>
</table>
```

## Applies To

ALL markdown files: docs, design docs, README, rules, guides.
