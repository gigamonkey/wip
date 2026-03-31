# CLAUDE.md

## What This Is

WIP-Server is a Flask + HTMX web app for managing work-in-progress tasks across
multiple projects. Data is stored as markdown TODO.md files in each project
directory — no database.

## Running

```bash
uv sync                                    # install deps
uv run python server.py sample-config.json # start on port 5555
```

Config JSON points to project directories and sets the port.

## Stack

- **Backend:** Flask 3.1.3, Python 3.13, Jinja2 templates
- **Frontend:** HTMX 2.0.4, Pico CSS 2, Bootstrap Icons 1.11.3
- **Data:** Markdown TODO.md files (one per project)
- **Package manager:** uv

## Project Structure

```
server.py              Main Flask app: routes, template filters, mutations
wip.py                 Core library: markdown parsing, section management
templates/
  layout.html          Base template (nav, CDN links)
  dashboard.html       Main page: in-progress items + project grid
  project.html         Per-project detail page
  _all_sections.html   Partial: all 3 task sections + drag-drop JS
  _project_card.html   Partial: dashboard project tile
  _edit_form.html      Partial: inline edit form
static/
  style.css            All custom styles
sample-config.json     Example config with project paths
```

## Key Patterns

### HTMX Mutations

All task actions are POST requests that return a re-rendered `_all_sections.html`
partial. The standard pattern is:

```html
hx-post="/api/project/{name}/task/{action}"
hx-target="#all-sections"
hx-swap="innerHTML"
```

After HTMX swaps, `htmx:afterSwap` reinitializes drag-and-drop listeners.

### TODO.md Format

```markdown
# Project Name

Optional description text.

## In progress

- Active task

## Backlog

- Upcoming task

## Done

- Completed task (2026-03-30T19:47:07)
```

- Section matching is case-insensitive
- Done items get ISO-8601 timestamps appended automatically
- Item lookup uses substring matching (case-insensitive)

### Templates

- Pages extend `layout.html`
- Partials are prefixed with `_` and rendered server-side for HTMX swaps
- The `| markdown` Jinja2 filter renders inline markdown (strips wrapping `<p>` tags)

### JavaScript

All JS is vanilla, inlined in `_all_sections.html`:
- Drag-and-drop reordering (backlog only)
- Copy-to-clipboard
- Inline editing (double-click)
- Form toggling (add item, add project)

### CSS

- `.btn-sm` buttons use Bootstrap Icons (`<i class="bi bi-icon-name"></i>`)
- `.task-row` is flex: `.item-text` (flex: 1) + `.item-actions` (shrink: 0)
- Drag feedback uses `.drag-over-top` / `.drag-over-bottom` border classes

## API Routes

All mutation routes: `/api/project/{name}/task/{action}` where action is one of:
`add`, `start`, `done`, `return`, `reopen`, `edit`, `delete`, `reorder`, `reorder-all`

## No Tests

There are no automated tests. Verify changes manually in the browser.
