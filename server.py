#!/usr/bin/env python3
"""HTMX web app for managing work queues across multiple projects."""

import json
import os
import re
import sys
from pathlib import Path

from flask import Flask, render_template, request, abort, redirect, url_for
from markupsafe import Markup
import markdown as md

import wip

app = Flask(__name__)


@app.template_filter("markdown")
def markdown_filter(text):
    """Render inline markdown (no wrapping <p> tag for single-line content)."""
    html = md.markdown(text, extensions=["fenced_code"])
    # Strip wrapping <p>...</p> if it's a single paragraph
    html = html.strip()
    if html.startswith("<p>") and html.endswith("</p>") and html.count("<p>") == 1:
        html = html[3:-4]
    return Markup(html)

# Populated at startup from config file
PROJECTS = []
CONFIG_PATH = None


def load_config(path):
    """Load project config from JSON file."""
    with open(path) as f:
        config = json.load(f)
    projects = []
    for p in config["projects"]:
        projects.append({
            "name": p["name"],
            "home": os.path.expanduser(p["home"]),
        })
    return projects, config.get("port", 5555)


def get_project(name):
    """Look up a project by name, or abort 404."""
    for p in PROJECTS:
        if p["name"] == name:
            return p
    abort(404)


def read_todo(project):
    """Read and parse a project's TODO.md. Returns (text, path) or (None, None)."""
    todo_path = wip.resolve_todo_file(project["home"])
    if not todo_path:
        return None, None
    return todo_path.read_text(), todo_path


def read_todo_description(text):
    """Extract description from between the first # heading and first ## heading."""
    if not text:
        return ""
    desc_lines = []
    in_body = False
    for line in text.splitlines():
        if not in_body:
            if line.startswith("# "):
                in_body = True
            continue
        if line.startswith("## "):
            break
        desc_lines.append(line)
    return "\n".join(desc_lines).strip()


def get_section_items(text, section_name):
    """Get parsed todo items for a section. Returns list of dicts."""
    match = wip.find_section_case_insensitive(text, section_name)
    if not match:
        return []
    heading, sec_start, sec_end = match
    heading_end = text.index("\n", sec_start) + 1
    content = text[heading_end:sec_end]
    items = wip.parse_todo_items(content)
    result = []
    for item_text, is_checked, raw, start, end in items:
        result.append({
            "text": item_text,
            "checked": is_checked,
            "raw": raw,
        })
    return result


def project_summary(project):
    """Build a summary dict for a project (used by dashboard cards)."""
    text, todo_path = read_todo(project)
    summary = {
        "name": project["name"],
        "description": read_todo_description(text),
        "has_todo": text is not None,
        "in_progress": [],
        "up_next": [],
        "in_progress_count": 0,
        "up_next_count": 0,
    }
    if text:
        ip = get_section_items(text, "in progress")
        un = get_section_items(text, "backlog")
        summary["in_progress"] = ip[:3]
        summary["up_next"] = un[:1]
        summary["in_progress_count"] = len(ip)
        summary["up_next_count"] = len(un)
    return summary


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@app.route("/")
def dashboard():
    in_progress = []
    backlog_by_project = []
    for project in PROJECTS:
        text, _ = read_todo(project)
        items_ip = []
        items_un = []
        if text:
            items_ip = [i for i in get_section_items(text, "in progress") if not i["checked"]]
            items_un = [i for i in get_section_items(text, "backlog") if not i["checked"]]
        for item in items_ip:
            in_progress.append({"project": project["name"], **item})
        total = len(items_un)
        backlog_by_project.append({
            "name": project["name"],
            "tasks": items_un[:3],
            "more": total - min(total, 3),
            "ip_count": len(items_ip),
            "total": total,
        })
    backlog_by_project.sort(key=lambda p: (p["ip_count"], p["total"]), reverse=True)
    return render_template("dashboard.html", in_progress=in_progress, backlog_by_project=backlog_by_project)


@app.route("/project/<name>")
def project_detail(name):
    project = get_project(name)
    text, todo_path = read_todo(project)
    sections = {}
    if text:
        for sec_name in ("in progress", "backlog", "done"):
            sections[sec_name] = get_section_items(text, sec_name)
    else:
        for sec_name in ("in progress", "backlog", "done"):
            sections[sec_name] = []
    description = read_todo_description(text)
    return render_template("project.html", project=project, description=description, sections=sections)


# ---------------------------------------------------------------------------
# HTMX partial routes
# ---------------------------------------------------------------------------

@app.route("/api/project/add", methods=["POST"])
def project_add():
    home = request.form.get("home", "").strip()
    if not home:
        return "Directory is required", 400

    expanded = os.path.expanduser(home)
    if not os.path.isdir(expanded):
        return f"Directory not found: {home}", 400

    # Derive name from directory basename
    name = os.path.basename(expanded.rstrip("/"))

    # Check for duplicates
    for p in PROJECTS:
        if p["name"] == name:
            return f"Project '{name}' already exists", 400

    # Add to in-memory list
    project = {"name": name, "home": expanded}
    PROJECTS.append(project)

    # Persist to config file
    config_path = app.config["CONFIG_PATH"]
    with open(config_path) as f:
        config = json.load(f)
    config["projects"].append({"name": name, "home": home})
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    return redirect("/")


@app.route("/api/project/<name>/card")
def project_card(name):
    project = get_project(name)
    summary = project_summary(project)
    return render_template("_project_card.html", p=summary)


@app.route("/api/project/<name>/sections")
def project_sections(name):
    """Re-render all three sections (used after mutations that affect multiple sections)."""
    project = get_project(name)
    text, _ = read_todo(project)
    sections = {}
    if text:
        for sec_name in ("in progress", "backlog", "done"):
            sections[sec_name] = get_section_items(text, sec_name)
    else:
        for sec_name in ("in progress", "backlog", "done"):
            sections[sec_name] = []
    return render_template("_all_sections.html", project=project, sections=sections)


@app.route("/api/project/<name>/task/add", methods=["POST"])
def task_add(name):
    project = get_project(name)
    item = request.form.get("item", "").strip()
    section = request.form.get("section", "backlog").strip()
    if not item:
        return "Item text required", 400

    todo_path = wip.resolve_todo_file(project["home"])
    if not todo_path:
        todo_path = wip.create_todo_file(project["home"])

    text = todo_path.read_text()

    # Ensure section exists
    if section.lower() == "backlog":
        text, match = wip.ensure_backlog_section(text)
    elif section.lower() == "in progress":
        text, match = wip.ensure_in_progress_section(text)
    else:
        match = wip.find_section_case_insensitive(text, section)

    if not match:
        return f"Section '{section}' not found", 400

    heading, sec_start, sec_end = match
    insert_pos = sec_end
    bullet = f"- {item}\n\n"
    text = text[:insert_pos].rstrip("\n") + "\n\n" + bullet + text[insert_pos:].lstrip("\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = wip.ensure_trailing_newline(text)
    todo_path.write_text(text)

    return _render_after_mutation(project)


@app.route("/api/project/<name>/task/done", methods=["POST"])
def task_done(name):
    project = get_project(name)
    item_text = request.form.get("item", "").strip()
    if not item_text:
        return "Item text required", 400

    todo_path = wip.resolve_todo_file(project["home"])
    if not todo_path:
        return "No TODO.md found", 404

    text = todo_path.read_text()
    found = _find_item_in_sections(text, item_text, exclude=["done"])
    if not found:
        return f"Item not found: {item_text}", 404

    src_heading, heading_end, matched_text, raw, item_start, item_end = found

    # Remove from source
    abs_start = heading_end + item_start
    abs_end = heading_end + item_end
    text = text[:abs_start] + text[abs_end:]

    # Append to Done section (raw is used as-is, no checkbox transformation)
    done_sec = wip.get_section_content(text, "Done")
    if not done_sec:
        text = text.rstrip("\n") + "\n\n## Done\n\n"
        done_sec = wip.get_section_content(text, "Done")

    done_heading_end, done_end, _ = done_sec
    text = text[:done_end].rstrip("\n") + "\n\n" + raw.rstrip("\n") + "\n\n" + text[done_end:].lstrip("\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = wip.ensure_trailing_newline(text)
    todo_path.write_text(text)

    return _render_after_mutation(project)


@app.route("/api/project/<name>/task/return", methods=["POST"])
def task_return(name):
    """Move an item from In progress back to the top of Backlog."""
    project = get_project(name)
    item_text = request.form.get("item", "").strip()
    if not item_text:
        return "Item text required", 400

    todo_path = wip.resolve_todo_file(project["home"])
    if not todo_path:
        return "No TODO.md found", 404

    text = todo_path.read_text()

    # Find in In progress
    match = wip.find_section_case_insensitive(text, "in progress")
    if not match:
        return "No 'In progress' section", 404

    heading, sec_start, sec_end = match
    heading_end = text.index("\n", sec_start) + 1
    content = text[heading_end:sec_end]
    items = wip.parse_todo_items(content)

    found = None
    for t, checked, raw, s, e in items:
        if item_text.lower() in t.lower():
            found = (t, raw, s, e)
            break

    if not found:
        return f"Item not found in In progress: {item_text}", 404

    item_t, raw, item_start, item_end = found

    # Remove from In progress
    abs_start = heading_end + item_start
    abs_end = heading_end + item_end
    text = text[:abs_start] + text[abs_end:]
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Add to top of Backlog
    text, un_match = wip.ensure_backlog_section(text)
    _, un_start, un_end = un_match
    un_heading_end = text.index("\n", un_start) + 1
    text = text[:un_heading_end] + "\n" + raw.rstrip("\n") + "\n\n" + text[un_heading_end:].lstrip("\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = wip.ensure_trailing_newline(text)
    todo_path.write_text(text)

    return _render_after_mutation(project)


@app.route("/api/project/<name>/task/start", methods=["POST"])
def task_start(name):
    project = get_project(name)
    item_text = request.form.get("item", "").strip()
    if not item_text:
        return "Item text required", 400

    todo_path = wip.resolve_todo_file(project["home"])
    if not todo_path:
        return "No TODO.md found", 404

    text = todo_path.read_text()

    # Find in Backlog
    match = wip.find_section_case_insensitive(text, "backlog")
    if not match:
        return "No 'Backlog' section", 404

    heading, sec_start, sec_end = match
    heading_end = text.index("\n", sec_start) + 1
    content = text[heading_end:sec_end]
    items = wip.parse_todo_items(content)

    found = None
    for t, checked, raw, s, e in items:
        if item_text.lower() in t.lower():
            found = (t, raw, s, e)
            break

    if not found:
        return f"Item not found in Backlog: {item_text}", 404

    item_t, raw, item_start, item_end = found

    # Remove from Backlog
    abs_start = heading_end + item_start
    abs_end = heading_end + item_end
    text = text[:abs_start] + text[abs_end:]
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Add to In progress
    text, ip_match = wip.ensure_in_progress_section(text)
    _, ip_start, ip_end = ip_match
    text = text[:ip_end].rstrip("\n") + "\n\n" + raw.rstrip("\n") + "\n\n" + text[ip_end:].lstrip("\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = wip.ensure_trailing_newline(text)
    todo_path.write_text(text)

    return _render_after_mutation(project)


@app.route("/api/project/<name>/task/edit", methods=["POST"])
def task_edit(name):
    project = get_project(name)
    old_text = request.form.get("item", "").strip()
    new_text = request.form.get("new_text", "").strip()
    if not old_text or not new_text:
        return "Both item and new_text required", 400

    todo_path = wip.resolve_todo_file(project["home"])
    if not todo_path:
        return "No TODO.md found", 404

    text = todo_path.read_text()
    found = _find_item_in_sections(text, old_text, exclude=["done"])
    if not found:
        return f"Item not found: {old_text}", 404

    src_heading, heading_end, matched_text, raw, item_start, item_end = found

    new_raw = "- " + new_text + "\n"

    abs_start = heading_end + item_start
    abs_end = heading_end + item_end
    text = text[:abs_start] + new_raw + text[abs_end:]
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = wip.ensure_trailing_newline(text)
    todo_path.write_text(text)

    return _render_after_mutation(project)


@app.route("/api/project/<name>/task/delete", methods=["POST"])
def task_delete(name):
    project = get_project(name)
    item_text = request.form.get("item", "").strip()
    section = request.form.get("section", "").strip()
    if not item_text:
        return "Item text required", 400

    todo_path = wip.resolve_todo_file(project["home"])
    if not todo_path:
        return "No TODO.md found", 404

    text = todo_path.read_text()

    if section:
        found = _find_item_in_section(text, item_text, section)
    else:
        found = _find_item_in_sections(text, item_text)

    if not found:
        return f"Item not found: {item_text}", 404

    src_heading, heading_end, matched_text, raw, item_start, item_end = found
    abs_start = heading_end + item_start
    abs_end = heading_end + item_end
    text = text[:abs_start] + text[abs_end:]
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = wip.ensure_trailing_newline(text)
    todo_path.write_text(text)

    return _render_after_mutation(project)


@app.route("/api/project/<name>/task/reorder", methods=["POST"])
def task_reorder(name):
    project = get_project(name)
    item_text = request.form.get("item", "").strip()
    direction = request.form.get("direction", "").strip()
    section = request.form.get("section", "").strip()
    if not item_text or direction not in ("up", "down") or not section:
        return "item, direction (up/down), and section required", 400

    todo_path = wip.resolve_todo_file(project["home"])
    if not todo_path:
        return "No TODO.md found", 404

    text = todo_path.read_text()
    match = wip.find_section_case_insensitive(text, section)
    if not match:
        return f"Section '{section}' not found", 404

    heading, sec_start, sec_end = match
    heading_end = text.index("\n", sec_start) + 1
    content = text[heading_end:sec_end]
    items = wip.parse_todo_items(content)

    # Find the item index
    target_idx = None
    for i, (t, checked, raw, s, e) in enumerate(items):
        if item_text.lower() in t.lower():
            target_idx = i
            break

    if target_idx is None:
        return f"Item not found in {section}", 404

    swap_idx = target_idx - 1 if direction == "up" else target_idx + 1
    if swap_idx < 0 or swap_idx >= len(items):
        # Already at boundary, just re-render
        return _render_after_mutation(project)

    # Swap by rebuilding the section content
    raw_items = [raw for _, _, raw, _, _ in items]
    raw_items[target_idx], raw_items[swap_idx] = raw_items[swap_idx], raw_items[target_idx]

    # Rebuild section content: keep any non-item text before items, then items
    first_item_start = items[0][3] if items else len(content)
    preamble = content[:first_item_start]
    new_content = preamble + "\n\n".join(r.rstrip("\n") for r in raw_items) + "\n"

    text = text[:heading_end] + new_content + "\n" + text[sec_end:].lstrip("\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = wip.ensure_trailing_newline(text)
    todo_path.write_text(text)

    return _render_after_mutation(project)


@app.route("/api/project/<name>/task/reorder-all", methods=["POST"])
def task_reorder_all(name):
    """Reorder all items in a section. Accepts JSON body with {section, order} where
    order is a list of 0-based indices representing the new order."""
    project = get_project(name)
    data = request.get_json()
    if not data:
        return "JSON body required", 400
    section = data.get("section", "").strip()
    order = data.get("order", [])
    if not section or not order:
        return "section and order required", 400

    todo_path = wip.resolve_todo_file(project["home"])
    if not todo_path:
        return "No TODO.md found", 404

    text = todo_path.read_text()
    match = wip.find_section_case_insensitive(text, section)
    if not match:
        return f"Section '{section}' not found", 404

    heading, sec_start, sec_end = match
    heading_end = text.index("\n", sec_start) + 1
    content = text[heading_end:sec_end]
    items = wip.parse_todo_items(content)

    raw_items = [raw for _, _, raw, _, _ in items]
    if sorted(order) != list(range(len(raw_items))):
        return "Invalid order", 400

    reordered = [raw_items[i] for i in order]

    first_item_start = items[0][3] if items else len(content)
    preamble = content[:first_item_start]
    new_content = preamble + "\n\n".join(r.rstrip("\n") for r in reordered) + "\n"

    text = text[:heading_end] + new_content + "\n" + text[sec_end:].lstrip("\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = wip.ensure_trailing_newline(text)
    todo_path.write_text(text)

    return _render_project_sections(project)


@app.route("/api/project/<name>/task/edit-form", methods=["GET"])
def task_edit_form(name):
    """Return an inline edit form for a task item."""
    project = get_project(name)
    item_text = request.args.get("item", "")
    section = request.args.get("section", "")
    return render_template("_edit_form.html", project=project, item=item_text, section=section)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_item_in_section(text, search_text, section_name):
    """Find an item in a specific section. Returns tuple or None."""
    match = wip.find_section_case_insensitive(text, section_name)
    if not match:
        return None
    heading, sec_start, sec_end = match
    heading_end = text.index("\n", sec_start) + 1
    content = text[heading_end:sec_end]
    items = wip.parse_todo_items(content)
    for item_text, is_checked, raw, item_start, item_end in items:
        if search_text.lower() in item_text.lower():
            return (heading, heading_end, item_text, raw, item_start, item_end)
    return None


def _find_item_in_sections(text, search_text, exclude=None):
    """Find an item across sections. Returns tuple or None."""
    exclude = [e.lower() for e in (exclude or [])]
    for heading, sec_start, sec_end, _ in wip.find_sections(text):
        if heading.lower() in exclude:
            continue
        heading_end = text.index("\n", sec_start) + 1
        content = text[heading_end:sec_end]
        items = wip.parse_todo_items(content)
        for item_text, is_checked, raw, item_start, item_end in items:
            if search_text.lower() in item_text.lower():
                return (heading, heading_end, item_text, raw, item_start, item_end)
    return None


def _render_after_mutation(project):
    """After a mutation, re-render either the dashboard or project sections."""
    redir = request.form.get("redirect", "")
    if redir == "/":
        return redirect("/")
    return _render_project_sections(project)


def _render_project_sections(project):
    """Re-read TODO.md and render all sections partial."""
    text, _ = read_todo(project)
    sections = {}
    if text:
        for sec_name in ("in progress", "backlog", "done"):
            sections[sec_name] = get_section_items(text, sec_name)
    else:
        for sec_name in ("in progress", "backlog", "done"):
            sections[sec_name] = []
    return render_template("_all_sections.html", project=project, sections=sections)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python server.py <config.json>", file=sys.stderr)
        sys.exit(1)
    CONFIG_PATH = os.path.abspath(sys.argv[1])
    PROJECTS, port = load_config(CONFIG_PATH)
    app.config["CONFIG_PATH"] = CONFIG_PATH
    print(f"Loaded {len(PROJECTS)} projects, serving on http://localhost:{port}")
    for p in PROJECTS:
        print(f"  - {p['name']}: {p['home']}")
    app.run(host="127.0.0.1", port=port, debug=True)
