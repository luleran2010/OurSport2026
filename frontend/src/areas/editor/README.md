# Editor area (E1–E3)

Pages for news editors, who write club news and review AI-written stories before they are published.
Same pattern as the other areas: pages and a `routes.jsx` here, layout in `app/layouts/`, access through `RoleGuard`.

- **E1 Review queue** (`/editor`, `QueueView.jsx`): filters (assigned, reason, sport, event, language, waiting time),
  dense table (waiting time amber over 30 min, red over 2 h), "Take next", row → E2. Reloads every 15 s.
  Shortcuts: `j`/`k` or arrows move, `Enter` opens, `n` take next, `r` refresh, `/` filters, `x` clear filters, `?` help.
- **E2 Review item** (`/editor/items/{id}`, `ReviewItemView.jsx`): the text with the checker's marks (underlined = tied to
  facts, hover for the ids; red = flagged, with the reason), the evidence (fact sheet, match data, rule version, history),
  and a sticky footer: Approve and publish (`a`), Edit then approve (`e`: save, re-check, publish only if it passes),
  Reject (`r`, then confirm), Send back to regenerate (`s`). `j`/`k` next/previous item, `u` back to the queue.
  With red flags left or the text changed since the last check, approving needs "I verified this manually"; ticked,
  it stands in for the checker (in edit mode "Save and approve" publishes without running it).
- **E3 Published content** (`/editor/published`, `PublishedView.jsx`): error reports from fans and clubs (open first;
  Correct → E2 on the report's item, or Resolve inline as fixed / rejected with a note), and every published story
  (search, date, event, AI / manual, corrected) with View, Correct (E2 on `fix-{storyId}`; publishing needs a note for
  readers and shows "Corrected on {date}" on the story) and Unpublish (reason required). Shortcuts: `/`, `j`/`k`, `c`, `x`, `?`.

**Data:** the desk runs on the backend's v1 editorial API through `api/editor.js` (queue, review item, claim and
take-next, edit with If-Match, check, approve, reject, regenerate, unpublish, `GET /editor/stories`, corrections).
The backend serves plain lists; the desk's filters, counts and pages are worked out in `editor.js`. The backend does
not record that a story was verified manually (only that an editor approved it), and a regenerate is checked at once (published
when it passes, back in the queue when it does not). For local work, `uv run python -m app.scripts.review_demo` in
`backend/` puts AI stories with a wrong claim in the queue.
