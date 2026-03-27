---
description: Regenerate PNG when draw.io diagrams are modified
---

# Draw.io PNG Export Rule

Whenever a `.drawio` file is modified in the repository, Cascade MUST regenerate the corresponding PNG file.

## Command

```bash
/Applications/draw.io.app/Contents/MacOS/draw.io --export --format png --output <output.png> <input.drawio>
```

## Example

If `docs/architecture/omnibor-analysis-workflow.drawio` is modified:

```bash
/Applications/draw.io.app/Contents/MacOS/draw.io --export --format png --output docs/architecture/omnibor-analysis-workflow.png docs/architecture/omnibor-analysis-workflow.drawio
```

## Workflow

1. After modifying any `.drawio` file, run the export command
2. Commit both the `.drawio` and `.png` files together
3. The PNG should have the same base name as the drawio file

## Known Locations

- `docs/architecture/omnibor-analysis-workflow.drawio` → `docs/architecture/omnibor-analysis-workflow.png`
