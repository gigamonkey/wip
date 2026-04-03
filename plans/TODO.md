# TODO

WIP management server

## In progress

## Backlog

- Add the ability to pin projects on the dashboard page even if they would otherwise be hidden.

- Add a sidebar menu of all the projects with the same information as on their dashboard tiles but maybe with just the numbers in the pills.

- Make the show all option persistant in local storage.

- Move the TODOs into a SQLite database.

- Show all counts on dashboard tiles, even if they are zero. And format like "In progress: 0", "backlog: 3", tec.

## Done

- Move project descriptions into per-project TODO files. The text in the TODO file after the first `#` header should be taken as the projects description. Which means we don't need to collect the description when adding a new project.

- Change the dashbord so there's a + icon next to the Show all item in the Projects header. When clicked it should open up an inline textbox for typing a directory to add as a project. This replaces the Add Project form at the bottom of the page.

- Add timestamps to done items and group by date. (2026-03-30T15:41:27)

- Add a button to Done items to put them back into In progress. The layout should be the asme as for buttons in the other two sections. (2026-03-30T16:42:28)

- Add bootstrap icons to this project and use them for buttons. (2026-03-30T19:47:07)

- Write a CLAUDE.md for this project. (2026-03-30T19:53:55)

- Add clipboard to copy button on In progress items too. (2026-03-31T10:13:15)

- There's still a very subtle difference between the three buttons next to the backlog items, I think because the first and third are wrapped in a `<form>` while the clipboard is just a `<button>`. As a consequence they are slightly different sizes and thus don't line up quite right. (2026-03-31T10:23:44)

- For each project look in the `plans/` directory and if there are any `.md` files there other than `TODO.md` add a "Plans" section on the project page in between "Backlog" and "Done" with links to the pages that render the plan files as HTML. (2026-03-31T11:29:18)

- Get rid of pico.css and simplify HTML. (2026-03-31T15:35:30)

- Markdown rendering doesn't seem to know how to render tables. (2026-03-31T17:33:25)

- Add git status to project pages. (2026-04-01T13:17:02)

- Change the editing of items and writing of new items to just be in place rather than in a text box. Editing ends when the user types enter/return. Also allow editing in both "In progress" and "Backlog". (2026-04-02T09:16:43)

