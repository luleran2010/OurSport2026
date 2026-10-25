# Frontend source layout

```
src/
  main.jsx        entry: router + styles + <App />
  api/            API client (client.js) and data hooks (useLoad, useMe, useCatalogData, useNotifications)
  app/            App.jsx, router.js (path <-> view), AppProviders, RoleGuard, layouts per area
    layouts/      FanLayout (+ fan/ sidebar, top bar, news feed)
    providers/    React contexts: catalog, me
  areas/
    fan/          F1–F13 pages, routes.jsx, fan-only components/
    scorer/       S1–S2 (+ offline queue)   — not started
    publisher/    P1–P5                     — not started
    editor/       E1–E3                     — not started
  components/     components shared by several areas (TeamBadge, MatchRow, ScenarioCard, StoryCard, Modal…)
  live/           live data: feed stream (SSE) and match WebSocket with reconnect (no sequence numbers yet)
  i18n/           en.json, fi.json, bn.json + t() / useT()
  styles/         tokens.css (design tokens), base.css, app.css
  utils/          time.js (always Europe/Helsinki), format.js
```

Rules of thumb: a page belongs to its area; a component used by two areas moves to `components/`;
anything that talks to the server lives in `api/` (or `live/` for streams).

Public organisation pages use the real v1 API. There is no separate club portal in the frontend;
event setup and management live in the publisher area.
