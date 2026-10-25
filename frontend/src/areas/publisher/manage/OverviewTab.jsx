import { clockTime, dayLabel, timeAgo } from '../../../utils/time'

function score(m) {
  return m.score ? `${m.score[0]}–${m.score[1]}` : 'v'
}

export default function OverviewTab({ d, setTab }) {
  const now = d.updatedAt
  const live = d.matches.filter((r) => r.status === 'live')
  const awaiting = d.matches.filter((r) => r.status === 'awaiting_result')
  const next = d.matches.filter((r) => r.status === 'upcoming').slice(0, 6)
  const recent = d.matches.filter((r) => r.status === 'finished').sort((a, b) => (b.match.endedAt ?? 0) - (a.match.endedAt ?? 0)).slice(0, 4)
  return (
    <div className="ev-overview">
      <div className="kpi-grid">
        <div className="kpi"><span className="kpi-label">Matches played</span><span className="kpi-value">{d.counts.played} / {d.counts.total}</span></div>
        <div className="kpi"><span className="kpi-label">Live now</span><span className="kpi-value">{d.counts.live}</span></div>
        <button className={`kpi kpi--btn${d.counts.awaiting_result ? ' kpi--warn' : ''}`} onClick={() => setTab('fixtures', { show: 'result' })}>
          <span className="kpi-label">Results to enter</span><span className="kpi-value">{d.counts.awaiting_result}</span>
        </button>
        <button className={`kpi kpi--btn${d.counts.no_scorer ? ' kpi--warn' : ''}`} onClick={() => setTab('fixtures', { show: 'noscorer' })}>
          <span className="kpi-label">Live-data matches without a scorer</span><span className="kpi-value">{d.counts.no_scorer}</span>
        </button>
      </div>

      {awaiting.length > 0 && (
        <div className="ev-alert" role="status">
          <b>{awaiting.length} result{awaiting.length > 1 ? 's' : ''} to enter.</b> These results-only games have started.{' '}
          <button className="link-btn link-btn--accent" onClick={() => setTab('fixtures', { show: 'result' })}>Enter results →</button>
        </div>
      )}

      <div className="ev-cols">
        <section>
          <h2 className="ev-h2">Live now</h2>
          {live.length === 0 ? <p className="page-sub">No match is live right now.</p> : (
            <ul className="ev-list">
              {live.map((r) => (
                <li key={r.match.id} className="ev-item ev-item--live">
                  <span className="live-dot" aria-hidden="true" />
                  <span className="ev-item-main"><b>{r.match.home.name} {score(r.match)} {r.match.away.name}</b>
                    <span className="ev-sub">{r.group} · {r.match.period ?? 'Live'} · {r.match.venue}</span></span>
                  <span className="ev-sub">{r.scorer ? `Scorer: ${r.scorer.name}` : r.match.dataLevel === 'live' ? 'No scorer' : 'Results only'}</span>
                </li>
              ))}
            </ul>
          )}
          <h2 className="ev-h2">Next matches</h2>
          {next.length === 0 ? <p className="page-sub">No more matches scheduled.</p> : (
            <ul className="ev-list">
              {next.map((r) => (
                <li key={r.match.id} className="ev-item">
                  <span className="ev-time"><b>{clockTime(r.match.startsAt)}</b><span className="ev-sub">{dayLabel(r.match.startsAt, now)}</span></span>
                  <span className="ev-item-main">{r.match.home.name} v {r.match.away.name}<span className="ev-sub">{r.group} · {r.match.venue}</span></span>
                  <span className={`ev-sub${!r.scorer && r.match.dataLevel === 'live' ? ' ev-warn' : ''}`}>
                    {r.scorer ? `Scorer: ${r.scorer.name}` : r.match.dataLevel === 'live' ? 'No scorer yet' : 'Results only'}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section>
          <h2 className="ev-h2">Latest results</h2>
          {recent.length === 0 ? <p className="page-sub">No results yet.</p> : (
            <ul className="ev-list">
              {recent.map((r) => (
                <li key={r.match.id} className="ev-item">
                  <span className="ev-item-main"><b>{r.match.home.name} {score(r.match)} {r.match.away.name}</b>
                    <span className="ev-sub">{r.group} · {timeAgo(r.match.endedAt, now)}{r.match.correction ? ' · corrected' : ''}</span></span>
                </li>
              ))}
            </ul>
          )}
          <h2 className="ev-h2">Format</h2>
          <p className="page-sub">{d.format}</p>
          <p className="page-sub">
            Content in {d.settings.languages.map((l) => ({ fi: 'Finnish', en: 'English', bn: 'Bangla' }[l])).join(', ')} ·{' '}
            {d.settings.reviewEnabled ? 'you review AI texts first' : 'AI texts go out after the automatic check'} ·{' '}
            {d.settings.canPublish ? 'your posts publish directly' : 'your posts go to the OurSport editors first'}
          </p>
        </section>
      </div>
    </div>
  )
}
