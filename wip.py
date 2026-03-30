#!/usr/bin/env python3
"""CLI for manipulating ~/hacks/wip/WIP.md and per-project TODO.md files.

All commands output JSON to stdout. Mutating commands auto-clean empty sections.

WIP.md commands: list-projects, resolve-project, status, add, dispatch, done
TODO.md commands: todo-add, todo-next, todo-done
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

WIP_PATH = Path.home() / "hacks" / "wip" / "WIP.md"

# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def read_wip():
    return WIP_PATH.read_text()


def write_wip(text):
    WIP_PATH.write_text(text)


def parse_projects_table(text):
    """Return list of {name, description, home} from the markdown table."""
    projects = []
    in_table = False
    for line in text.splitlines():
        if line.startswith("|") and "project" in line.lower() and "home" in line.lower():
            in_table = True
            continue
        if in_table and line.startswith("|"):
            if set(line.replace("|", "").strip()) <= {"-", " "}:
                continue  # separator row
            cols = [c.strip() for c in line.split("|")]
            # split gives ['', col1, col2, col3, '']
            cols = [c for c in cols if c is not None]
            # filter empties from leading/trailing |
            cols = line.split("|")
            cols = [c.strip() for c in cols[1:-1]]  # drop first/last empty
            if len(cols) >= 3 and cols[0]:  # skip empty sentinel row
                projects.append({
                    "name": cols[0],
                    "description": cols[1],
                    "home": cols[2],
                })
        elif in_table and not line.startswith("|"):
            break
    return projects


def find_sections(text):
    """Return list of (heading_text, start_idx, end_idx) for ## headings."""
    sections = []
    lines = text.splitlines(keepends=True)
    i = 0
    while i < len(lines):
        m = re.match(r"^## (.+)$", lines[i].rstrip())
        if m:
            start = sum(len(l) for l in lines[:i])
            sections.append((m.group(1).strip(), start, i))
        i += 1
    # set end positions
    result = []
    for idx, (heading, char_start, line_idx) in enumerate(sections):
        if idx + 1 < len(sections):
            char_end = sections[idx + 1][1]
        else:
            char_end = len(text)
        result.append((heading, char_start, char_end, line_idx))
    return result


def get_section_content(text, heading):
    """Return (start, end, content) for a ## heading, or None."""
    for h, start, end, _ in find_sections(text):
        if h == heading:
            # content starts after the heading line
            heading_end = text.index("\n", start) + 1
            return heading_end, end, text[heading_end:end]
    return None


def parse_items(content):
    """Parse bullet items from section content. Returns list of (text, start_offset, end_offset)."""
    items = []
    lines = content.splitlines(keepends=True)
    i = 0
    while i < len(lines):
        if lines[i].startswith("- "):
            item_start = sum(len(l) for l in lines[:i])
            item_lines = [lines[i]]
            j = i + 1
            # continuation lines are indented
            while j < len(lines) and lines[j].startswith("  ") and not lines[j].startswith("- "):
                item_lines.append(lines[j])
                j += 1
            raw = "".join(item_lines).strip()
            # Strip leading "- " for the text
            item_text = raw[2:] if raw.startswith("- ") else raw
            item_end = sum(len(l) for l in lines[:j])
            items.append((item_text, item_start, item_end))
            i = j
        else:
            i += 1
    return items


def remove_text_range(text, abs_start, abs_end):
    """Remove a range and collapse excess blank lines."""
    result = text[:abs_start] + text[abs_end:]
    # collapse triple+ newlines to double
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result


def cleanup_empty_sections(text):
    """Remove ## project sections that have no items. Preserve In progress and Uncategorized."""
    protected = {"In progress", "Uncategorized"}
    changed = True
    while changed:
        changed = False
        for heading, start, end, _ in find_sections(text):
            if heading in protected:
                continue
            heading_end = text.index("\n", start) + 1
            content = text[heading_end:end]
            items = parse_items(content)
            if not items:
                text = text[:start] + text[end:]
                text = re.sub(r"\n{3,}", "\n\n", text)
                changed = True
                break
    return text


def ensure_trailing_newline(text):
    if text and not text.endswith("\n"):
        text += "\n"
    return text


# ---------------------------------------------------------------------------
# Section insertion point helpers
# ---------------------------------------------------------------------------

def find_insert_before_uncategorized(text):
    """Return char position just before ## Uncategorized (for creating new project sections)."""
    for heading, start, _, _ in find_sections(text):
        if heading == "Uncategorized":
            return start
    return len(text)


def find_first_project_section_start(text):
    """Return char position of the first ## heading that isn't 'In progress'."""
    for heading, start, _, _ in find_sections(text):
        if heading != "In progress":
            return start
    return len(text)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_list_projects(args):
    text = read_wip()
    projects = parse_projects_table(text)
    print(json.dumps(projects, indent=2))


def cmd_resolve_project(args):
    text = read_wip()
    projects = parse_projects_table(text)
    cwd = os.path.abspath(os.path.expanduser(args.cwd))
    for p in projects:
        home = os.path.abspath(os.path.expanduser(p["home"]))
        if cwd == home or cwd.startswith(home + os.sep):
            print(json.dumps({"project": p["name"], "home": p["home"]}))
            return
    print(json.dumps({"project": "", "home": ""}))


def cmd_status(args):
    text = read_wip()
    result = {"in_progress": [], "next": [], "uncategorized": []}

    # In progress items
    sec = get_section_content(text, "In progress")
    if sec:
        _, _, content = sec
        for item_text, _, _ in parse_items(content):
            m = re.match(r"^\*\*(.+?)\*\*\s*(.*)", item_text, re.DOTALL)
            if m:
                result["in_progress"].append({
                    "project": m.group(1),
                    "text": m.group(2).strip(),
                })
            else:
                result["in_progress"].append({"project": "", "text": item_text})

    # Project sections
    projects = parse_projects_table(text)
    project_names = {p["name"] for p in projects}
    for heading, start, end, _ in find_sections(text):
        if heading in ("In progress", "Uncategorized") or heading not in project_names:
            continue
        if args.project and heading != args.project:
            continue
        heading_end = text.index("\n", start) + 1
        content = text[heading_end:end]
        items = parse_items(content)
        if items:
            result["next"].append({"project": heading, "text": items[0][0]})

    # Uncategorized
    sec = get_section_content(text, "Uncategorized")
    if sec:
        _, _, content = sec
        for item_text, _, _ in parse_items(content):
            result["uncategorized"].append({"text": item_text})

    print(json.dumps(result, indent=2))


def cmd_add(args):
    text = read_wip()
    project = args.project
    item = args.item

    sec = get_section_content(text, project)
    if sec:
        heading_end, end, content = sec
        # Insert before the end of the section
        insert_pos = end
        # Walk backwards past trailing whitespace to find good insertion point
        bullet = f"- {item}\n\n"
        text = text[:insert_pos].rstrip("\n") + "\n\n" + bullet + text[insert_pos:].lstrip("\n")
    else:
        # Create section before Uncategorized
        insert_pos = find_insert_before_uncategorized(text)
        section = f"## {project}\n\n- {item}\n\n"
        text = text[:insert_pos] + section + text[insert_pos:]

    text = re.sub(r"\n{3,}", "\n\n", text)
    text = ensure_trailing_newline(text)
    write_wip(text)
    print(json.dumps({"ok": True, "project": project, "item": item}))


def cmd_dispatch(args):
    text = read_wip()
    project = args.project

    sec = get_section_content(text, project)
    if not sec:
        print(json.dumps({"error": f"No section found for project '{project}'"}))
        sys.exit(1)

    heading_end, end, content = sec
    items = parse_items(content)
    if not items:
        print(json.dumps({"error": f"No items in '{project}' section"}))
        sys.exit(1)

    item_text, item_start, item_end = items[0]
    clean_text = item_text

    # Remove item from project section
    abs_start = heading_end + item_start
    abs_end = heading_end + item_end
    text = remove_text_range(text, abs_start, abs_end)

    # Add to In progress
    in_progress = get_section_content(text, "In progress")
    if in_progress:
        ip_heading_end, ip_end, ip_content = in_progress
        insert_pos = ip_end
        bullet = f"- **{project}** {clean_text}\n\n"
        text = text[:insert_pos].rstrip("\n") + "\n\n" + bullet + text[insert_pos:].lstrip("\n")
    else:
        # Create In progress after table, before first project section
        insert_pos = find_first_project_section_start(text)
        section = f"## In progress\n\n- **{project}** {clean_text}\n\n"
        text = text[:insert_pos] + section + text[insert_pos:]

    text = cleanup_empty_sections(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = ensure_trailing_newline(text)
    write_wip(text)

    print(json.dumps({
        "ok": True,
        "project": project,
        "item": clean_text,
    }))


def cmd_done(args):
    text = read_wip()
    project = args.project

    sec = get_section_content(text, "In progress")
    if not sec:
        print(json.dumps({"error": "No 'In progress' section found"}))
        sys.exit(1)

    heading_end, end, content = sec
    items = parse_items(content)

    # Filter to items matching this project
    matches = []
    for i, (item_text, item_start, item_end) in enumerate(items):
        m = re.match(r"^\*\*(.+?)\*\*", item_text)
        if m and m.group(1) == project:
            matches.append((i, item_text, item_start, item_end))

    if not matches:
        print(json.dumps({"error": f"No in-progress items for '{project}'"}))
        sys.exit(1)

    if len(matches) == 1:
        idx = 0
    elif args.index is not None:
        idx = args.index
    else:
        # Multiple matches — return them for disambiguation
        items_list = []
        for i, (_, item_text, _, _) in enumerate(matches):
            m = re.match(r"^\*\*(.+?)\*\*\s*(.*)", item_text, re.DOTALL)
            items_list.append({"index": i, "text": m.group(2).strip() if m else item_text})
        print(json.dumps({"needs_disambiguation": True, "items": items_list}))
        return

    if idx < 0 or idx >= len(matches):
        print(json.dumps({"error": f"Invalid index {idx}, have {len(matches)} items"}))
        sys.exit(1)

    _, item_text, item_start, item_end = matches[idx]
    abs_start = heading_end + item_start
    abs_end = heading_end + item_end
    text = remove_text_range(text, abs_start, abs_end)

    text = cleanup_empty_sections(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = ensure_trailing_newline(text)
    write_wip(text)

    m = re.match(r"^\*\*(.+?)\*\*\s*(.*)", item_text, re.DOTALL)
    clean = m.group(2).strip() if m else item_text
    print(json.dumps({"ok": True, "project": project, "item": clean}))


# ---------------------------------------------------------------------------
# TODO.md helpers
# ---------------------------------------------------------------------------

def resolve_todo_file(home, file_override=None):
    """Find the TODO.md for a project. Returns Path or None."""
    if file_override:
        p = Path(os.path.expanduser(file_override))
        return p if p.exists() else None
    home = Path(os.path.expanduser(home))
    plans = home / "plans" / "TODO.md"
    root = home / "TODO.md"
    if plans.exists():
        return plans
    if root.exists():
        return root
    return None


def create_todo_file(home):
    """Create a basic plans/TODO.md and return its Path."""
    home = Path(os.path.expanduser(home))
    plans_dir = home / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    path = plans_dir / "TODO.md"
    path.write_text("# TODO\n\n## In progress\n\n## Up next\n\n## Done\n")
    return path


def find_section_case_insensitive(text, name):
    """Find first ## heading matching name case-insensitively (word match).
    Returns (heading_text, start, end) or None."""
    name_lower = name.lower().strip()
    for heading, start, end, _ in find_sections(text):
        # Match if the heading text equals or starts with the name
        h_lower = heading.lower().strip()
        if h_lower == name_lower or h_lower.startswith(name_lower + " "):
            return heading, start, end
    return None


def parse_todo_items(content):
    """Parse checkbox items from TODO section content.
    Returns list of (checkbox_text, is_checked, raw_lines, start_offset, end_offset).
    checkbox_text has the '[ ] ' or '[x] ' prefix stripped."""
    items = []
    lines = content.splitlines(keepends=True)
    i = 0
    while i < len(lines):
        m = re.match(r"^- \[([ x])\] (.*)$", lines[i].rstrip("\n"))
        if m:
            is_checked = m.group(1) == "x"
            item_start = sum(len(l) for l in lines[:i])
            item_lines = [lines[i]]
            j = i + 1
            while j < len(lines) and re.match(r"^[ \t]", lines[j]) and not re.match(r"^- ", lines[j]):
                item_lines.append(lines[j])
                j += 1
            raw = "".join(item_lines)
            # Build the text without the checkbox prefix
            first_line = m.group(2)
            cont_lines = item_lines[1:]
            checkbox_text = first_line + "".join(cont_lines).rstrip("\n")
            item_end = sum(len(l) for l in lines[:j])
            items.append((checkbox_text, is_checked, raw, item_start, item_end))
            i = j
        else:
            i += 1
    return items


def get_section_instructions(content):
    """Return instruction text before the first bullet item in a section."""
    lines = content.splitlines(keepends=True)
    instruction_lines = []
    for line in lines:
        if line.startswith("- "):
            break
        instruction_lines.append(line)
    return "".join(instruction_lines).strip()


# ---------------------------------------------------------------------------
# TODO.md commands
# ---------------------------------------------------------------------------

def ensure_up_next_section(text):
    """Ensure ## Up next exists before ## Done. Returns updated text and section info."""
    match = find_section_case_insensitive(text, "up next")
    if match:
        return text, match
    # Create ## Up next before ## Done
    done_match = find_section_case_insensitive(text, "done")
    if done_match:
        _, done_start, _ = done_match
        text = text[:done_start] + "## Up next\n\n" + text[done_start:]
    else:
        text = text.rstrip("\n") + "\n\n## Up next\n\n"
    match = find_section_case_insensitive(text, "up next")
    return text, match


def ensure_in_progress_section(text):
    """Ensure ## In progress exists before ## Up next. Returns updated text and section info."""
    match = find_section_case_insensitive(text, "in progress")
    if match:
        return text, match
    # Create ## In progress before ## Up next (or Done if no Up next)
    up_next = find_section_case_insensitive(text, "up next")
    if up_next:
        _, insert_start, _ = up_next
    else:
        done = find_section_case_insensitive(text, "done")
        if done:
            _, insert_start, _ = done
        else:
            insert_start = len(text)
    text = text[:insert_start] + "## In progress\n\n" + text[insert_start:]
    match = find_section_case_insensitive(text, "in progress")
    return text, match


def cmd_todo_add(args):
    home = args.home
    todo_path = resolve_todo_file(home, args.file)
    if not todo_path:
        todo_path = create_todo_file(home)

    text = todo_path.read_text()
    section = args.section

    if section:
        match = find_section_case_insensitive(text, section)
        if not match:
            print(json.dumps({"error": f"No section matching '{section}' in {todo_path}"}))
            sys.exit(1)
        heading, sec_start, sec_end = match
    else:
        # Default to ## Up next, creating it if needed
        text, match = ensure_up_next_section(text)
        if not match:
            print(json.dumps({"error": f"Could not find or create 'Up next' section in {todo_path}"}))
            sys.exit(1)
        heading, sec_start, sec_end = match

    # Insert at end of section
    heading_end = text.index("\n", sec_start) + 1
    insert_pos = sec_end
    bullet = f"- [ ] {args.item}\n\n"
    text = text[:insert_pos].rstrip("\n") + "\n\n" + bullet + text[insert_pos:].lstrip("\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = ensure_trailing_newline(text)
    todo_path.write_text(text)

    print(json.dumps({
        "ok": True,
        "file": str(todo_path),
        "section": heading,
        "item": args.item,
    }))


def cmd_todo_start(args):
    """Move the first (or matched) item from ## Up next to ## In progress."""
    home = args.home
    todo_path = resolve_todo_file(home, args.file)
    if not todo_path:
        print(json.dumps({"error": f"No TODO.md found for home '{home}'"}))
        sys.exit(1)

    text = todo_path.read_text()

    # Find ## Up next
    up_next = find_section_case_insensitive(text, "up next")
    if not up_next:
        print(json.dumps({"error": "No 'Up next' section found"}))
        sys.exit(1)

    _, up_start, up_end = up_next
    heading_end = text.index("\n", up_start) + 1
    content = text[heading_end:up_end]
    items = parse_todo_items(content)
    unchecked = [(t, raw, s, e) for t, checked, raw, s, e in items if not checked]

    if not unchecked:
        print(json.dumps({"error": "No unchecked items in 'Up next' section"}))
        sys.exit(1)

    if args.item:
        search = args.item.strip().lower()
        matched = [(t, raw, s, e) for t, raw, s, e in unchecked if search in t.lower()]
        if not matched:
            print(json.dumps({"error": f"No unchecked item matching '{args.item}' in 'Up next'"}))
            sys.exit(1)
        item_text, raw, item_start, item_end = matched[0]
    else:
        item_text, raw, item_start, item_end = unchecked[0]

    # Remove from Up next
    abs_start = heading_end + item_start
    abs_end = heading_end + item_end
    text = text[:abs_start] + text[abs_end:]
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Ensure ## In progress exists
    text, ip_match = ensure_in_progress_section(text)
    _, ip_start, ip_end = ip_match
    ip_heading_end = text.index("\n", ip_start) + 1

    # Append to end of ## In progress
    insert_pos = ip_end
    text = text[:insert_pos].rstrip("\n") + "\n\n" + raw.rstrip("\n") + "\n\n" + text[insert_pos:].lstrip("\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = ensure_trailing_newline(text)
    todo_path.write_text(text)

    print(json.dumps({"ok": True, "file": str(todo_path), "item": item_text}))


def cmd_todo_next(args):
    home = args.home
    todo_path = resolve_todo_file(home, args.file)
    if not todo_path:
        print(json.dumps({"error": f"No TODO.md found for home '{home}'"}))
        sys.exit(1)

    text = todo_path.read_text()

    if args.section:
        # Find specific section
        match = find_section_case_insensitive(text, args.section)
        if not match:
            print(json.dumps({"error": f"No section matching '{args.section}' in {todo_path}"}))
            sys.exit(1)
        heading, sec_start, sec_end = match
        heading_end = text.index("\n", sec_start) + 1
        content = text[heading_end:sec_end]
        instructions = get_section_instructions(content)
        items = parse_todo_items(content)
        unchecked = [(t, raw) for t, checked, raw, _, _ in items if not checked]
        if not unchecked:
            print(json.dumps({
                "file": str(todo_path),
                "section": heading,
                "item": None,
                "instructions": instructions,
            }))
            return
        print(json.dumps({
            "file": str(todo_path),
            "section": heading,
            "item": unchecked[0][0],
            "instructions": instructions,
        }))
    else:
        # Check ## Up next for the next item to start
        up_match = find_section_case_insensitive(text, "up next")
        if up_match:
            _, up_start, up_end = up_match
            up_heading_end = text.index("\n", up_start) + 1
            up_content = text[up_heading_end:up_end]
            up_items = parse_todo_items(up_content)
            up_unchecked = [t for t, checked, _, _, _ in up_items if not checked]
            if up_unchecked:
                print(json.dumps({
                    "file": str(todo_path),
                    "section": "Up next",
                    "item": up_unchecked[0],
                }))
                return

        print(json.dumps({"file": str(todo_path), "item": None}))


def cmd_todo_done(args):
    home = args.home
    todo_path = resolve_todo_file(home, args.file)
    if not todo_path:
        print(json.dumps({"error": f"No TODO.md found for home '{home}'"}))
        sys.exit(1)

    text = todo_path.read_text()
    search_text = args.item.strip()

    def search_section(heading_name):
        match = find_section_case_insensitive(text, heading_name)
        if not match:
            return None
        _, sec_start, sec_end = match
        heading_end = text.index("\n", sec_start) + 1
        content = text[heading_end:sec_end]
        items = parse_todo_items(content)
        for item_text, is_checked, raw, item_start, item_end in items:
            if is_checked:
                continue
            if search_text.lower() in item_text.lower():
                return (heading_name, heading_end, item_text, raw, item_start, item_end)
        return None

    # Search ## In progress first, then all other non-Done sections
    found = search_section("in progress")
    if not found:
        for heading, sec_start, sec_end, _ in find_sections(text):
            if heading.lower() in ("done", "in progress"):
                continue
            heading_end = text.index("\n", sec_start) + 1
            content = text[heading_end:sec_end]
            items = parse_todo_items(content)
            for item_text, is_checked, raw, item_start, item_end in items:
                if is_checked:
                    continue
                if search_text.lower() in item_text.lower():
                    found = (heading, heading_end, item_text, raw, item_start, item_end)
                    break
            if found:
                break

    if not found:
        print(json.dumps({"error": f"No unchecked item matching '{search_text}'"}))
        sys.exit(1)

    src_heading, heading_end, item_text, raw, item_start, item_end = found

    # Build the done version of the item
    done_raw = raw.replace("- [ ] ", "- [x] ", 1)

    # If --plan provided, append plan link to the item
    plan_followup_needed = False
    if args.plan:
        plan_name = args.plan
        plan_link = f" (plan: [{plan_name}](plans/{plan_name}))"
        done_lines = done_raw.splitlines(keepends=True)
        done_lines[0] = done_lines[0].rstrip("\n") + plan_link + "\n"
        done_raw = "".join(done_lines)
        plan_followup_needed = True

    # Remove from source section
    abs_start = heading_end + item_start
    abs_end = heading_end + item_end
    text = text[:abs_start] + text[abs_end:]

    # Find Done section and append
    done_sec = get_section_content(text, "Done")
    if not done_sec:
        text = text.rstrip("\n") + "\n\n## Done\n\n"
        done_sec = get_section_content(text, "Done")

    done_heading_end, done_end, done_content = done_sec
    insert_pos = done_end
    text = text[:insert_pos].rstrip("\n") + "\n\n" + done_raw.rstrip("\n") + "\n\n" + text[insert_pos:].lstrip("\n")

    text = re.sub(r"\n{3,}", "\n\n", text)
    text = ensure_trailing_newline(text)
    todo_path.write_text(text)

    result = {
        "ok": True,
        "file": str(todo_path),
        "item": item_text,
        "from_section": src_heading,
    }
    if plan_followup_needed:
        result["plan_followup_needed"] = True
        result["plan"] = args.plan
    print(json.dumps(result))


def normalize_item_text(text):
    """Normalize item text for fuzzy matching: lowercase, collapse whitespace."""
    return re.sub(r"\s+", " ", text).strip().lower()


def cmd_check_progress(args):
    wip_text = read_wip()
    projects = parse_projects_table(wip_text)
    project_home = {p["name"]: p["home"] for p in projects}

    sec = get_section_content(wip_text, "In progress")
    if not sec:
        print(json.dumps({"clearable": [], "unresolved": []}))
        return

    _, _, content = sec
    in_progress = parse_items(content)

    clearable = []
    unresolved = []

    for item_text, _, _ in in_progress:
        m = re.match(r"^\*\*(.+?)\*\*\s*(.*)", item_text, re.DOTALL)
        if not m:
            unresolved.append({"project": "", "wip_item": item_text, "reason": "no project prefix"})
            continue

        project = m.group(1)
        wip_body = normalize_item_text(m.group(2))

        home = project_home.get(project)
        if not home:
            unresolved.append({"project": project, "wip_item": item_text, "reason": "project not in table"})
            continue

        todo_path = resolve_todo_file(home)
        if not todo_path:
            unresolved.append({"project": project, "wip_item": item_text, "reason": "no TODO.md found"})
            continue

        todo_text = todo_path.read_text()
        done_sec = get_section_content(todo_text, "Done")
        if not done_sec:
            unresolved.append({"project": project, "wip_item": item_text, "reason": "no Done section in TODO.md"})
            continue

        _, _, done_content = done_sec
        done_items = parse_todo_items(done_content)

        matched_todo = None
        for todo_text_item, is_checked, _, _, _ in done_items:
            if not is_checked:
                continue
            todo_norm = normalize_item_text(todo_text_item)
            # Match if either is a substring of the other (handles truncation/minor diffs)
            if wip_body in todo_norm or todo_norm in wip_body:
                matched_todo = todo_text_item
                break

        if matched_todo:
            clearable.append({
                "project": project,
                "wip_item": item_text,
                "todo_item": matched_todo,
            })
        else:
            unresolved.append({
                "project": project,
                "wip_item": item_text,
                "reason": "not found in Done section",
            })

    print(json.dumps({"clearable": clearable, "unresolved": unresolved}, indent=2))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="WIP.md CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list-projects")

    rp = sub.add_parser("resolve-project")
    rp.add_argument("--cwd", required=True)

    st = sub.add_parser("status")
    st.add_argument("--project", default="")

    add = sub.add_parser("add")
    add.add_argument("--project", required=True)
    add.add_argument("--item", required=True)

    disp = sub.add_parser("dispatch")
    disp.add_argument("--project", required=True)

    done = sub.add_parser("done")
    done.add_argument("--project", required=True)
    done.add_argument("--index", type=int, default=None)

    ta = sub.add_parser("todo-add")
    ta.add_argument("--home", required=True)
    ta.add_argument("--section", default="")
    ta.add_argument("--item", required=True)
    ta.add_argument("--file", default=None)

    ts = sub.add_parser("todo-start")
    ts.add_argument("--home", required=True)
    ts.add_argument("--item", default=None)
    ts.add_argument("--file", default=None)

    tn = sub.add_parser("todo-next")
    tn.add_argument("--home", required=True)
    tn.add_argument("--section", default="")
    tn.add_argument("--file", default=None)

    td = sub.add_parser("todo-done")
    td.add_argument("--home", required=True)
    td.add_argument("--item", required=True)
    td.add_argument("--plan", default=None)
    td.add_argument("--file", default=None)

    sub.add_parser("check-progress")

    args = parser.parse_args()

    cmds = {
        "list-projects": cmd_list_projects,
        "resolve-project": cmd_resolve_project,
        "status": cmd_status,
        "add": cmd_add,
        "dispatch": cmd_dispatch,
        "done": cmd_done,
        "todo-add": cmd_todo_add,
        "todo-start": cmd_todo_start,
        "todo-next": cmd_todo_next,
        "todo-done": cmd_todo_done,
        "check-progress": cmd_check_progress,
    }
    cmds[args.command](args)


if __name__ == "__main__":
    main()
