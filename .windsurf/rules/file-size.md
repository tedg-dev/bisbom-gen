# File Size Best Practices

## Guidelines
- **Python modules** should stay under **400 lines** of code (excluding blank lines and comments).
- If a module exceeds 400 lines, flag it for refactoring in your response.
- When flagging, suggest a decomposition strategy (e.g., extract classes, split HTML template from logic, separate constants).

## When to refactor
- Do NOT refactor proactively — always ask the user first.
- Complete the current task and merge before starting a refactor.
- Create a dedicated branch (e.g., `refactor/<module-name>`) for the refactoring work.

## Common decomposition patterns
- **HTML/JS template strings**: Extract into a separate template file or builder module.
- **Large f-strings with embedded JS**: Split into a template module with helper functions.
- **Multiple concerns in one file**: Separate data extraction, rendering, and CLI into distinct modules.
