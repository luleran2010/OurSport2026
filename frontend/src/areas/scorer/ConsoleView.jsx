import { useEffect, useState } from 'react'
import Modal from '../../components/Modal'
import TeamBadge from '../../components/TeamBadge'
import { project, useScoringConsole } from './useScoringConsole'
import { useWakeLock } from './useWakeLock'
import PlayerPicker from './PlayerPicker'

const CONTROL = new Set(['start', 'period_end', 'period_start'])

function useSecondTick(active) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [active])
  return now
}

function SyncIndicator({ queue, online, retryAt, now }) {
  const failed = queue.filter((q) => q.error).length
  const waiting = queue.length
  const tone = failed ? 'failed' : waiting ? 'queued' : 'synced'
  const text = failed
    ? `${failed} failed`
    : waiting
      ? `${waiting} queued${!online ? ' · offline' : retryAt && retryAt > now ? ` · retry ${Math.ceil((retryAt - now) / 1000)} s` : ''}`
      : online ? 'Synced' : 'Synced · offline'
  return (
    <span className={`sc-sync-pill sc-sync-pill--${tone}`} role="status" aria-live="polite">
      <span className="sc-dot" aria-hidden="true" />{text}
    </span>
  )
}

function Confirm({ open, title, children, confirmLabel, danger, onConfirm, onCancel }) {
  return (
    <Modal open={open} onClose={onCancel} labelledBy="sc-confirm-h">
      <div className="modal-body sc-confirm">
        <h2 id="sc-confirm-h">{title}</h2>
        {children}
        <div className="sc-confirm-actions">
          <button className="sc-btn sc-btn--ghost" onClick={onCancel}>Cancel</button>
          <button className={`sc-btn${danger ? ' sc-btn--danger' : ''}`} onClick={onConfirm}>{confirmLabel}</button>
        </div>
      </div>
    </Modal>
  )
}

export default function ConsoleView({ matchId, onNavigate }) {
  const c = useScoringConsole(matchId)
  const [batting, setBatting] = useState('home')
  const [picker, setPicker] = useState(null) // { type, team, followUp }
  const [confirm, setConfirm] = useState(null) // { kind: 'undo', event } | { kind: 'finish' }
  const [flash, setFlash] = useState('')
  const [result, setResult] = useState(['', ''])
  const live = Boolean(c.server && c.server.match.status !== 'finished')
  useWakeLock(live)
  const now = useSecondTick(live || c.queue.length > 0)

  if (!c.server || !c.types) {
    if (c.load.status === 'error') {
      const notMine = c.load.error?.status === 403
      return (
        <section className="sc-panel" role="alert">
          <h1>{notMine ? 'Not your match' : 'Can’t open the match'}</h1>
          <p>{notMine ? c.load.error.message : c.load.offline ? 'You’re offline and this match isn’t saved on the phone yet.' : c.load.error?.message}</p>
          {!notMine && <button className="sc-btn" onClick={c.reload}>Try again</button>}
          <button className="sc-btn sc-btn--ghost" onClick={() => onNavigate({ type: 'scorer' })}>← My matches</button>
        </section>
      )
    }
    return <p className="sc-muted" aria-busy="true">Opening the match…</p>
  }

  const s = c.server
  const t = c.types
  const m = s.match
  const v = project(s, c.queue, t)
  const byId = Object.fromEntries(t.eventTypes.map((e) => [e.id, e]))
  const side = (team) => (team === 'home' ? m.home : m.away)
  const rosters = { home: s.homeRoster, away: s.awayRoster, names: { home: m.home.name, away: m.away.name } }
  const playerLabel = (team, id) => {
    const p = (team === 'away' ? s.awayRoster : s.homeRoster).find((x) => x.id === id)
    return p ? (p.name ? `#${p.number} ${p.name}` : `#${p.number}`) : null
  }
  const recent = [...new Set(v.events.filter((e) => e.playerId).map((e) => e.playerId))].slice(0, 6)
  const cricket = t.pad === 'batting'
  const nextPeriod = t.periods[v.periodIndex + 1]
  const periodLabel = v.finished ? 'Full time' : !v.started ? 'Not started' : v.between ? `End of ${t.periods[v.periodIndex]}` : t.periods[v.periodIndex]
  const clockRunning = s.clock?.running && !v.between && !v.finished
  const minute = s.clock ? s.clock.baseMinute + (clockRunning ? Math.floor((now - s.clock.baseAt) / 60000) : 0) : null
  const overs = (side) => `${Math.floor(v.balls[side] / 6)}.${v.balls[side] % 6}`
  const scoreText = (i) => (cricket ? `${v.score[i]}/${v.wickets[i]}` : v.score[i])

  const say = (text) => {
    setFlash(text)
    setTimeout(() => setFlash((f) => (f === text ? '' : f)), 2500)
  }
  const record = async (et, team, playerId) => {
    await c.record(et.id, et.team ? team : null, playerId)
    say(`✓ ${et.label}${et.team ? ` · ${side(team).short}` : ''}${playerId ? ` · ${playerLabel(team, playerId)}` : ''}`)
  }
  const tap = (et, team) => {
    if (et.player !== 'none') setPicker({ et, team, optional: et.player === 'optional', skipLabel: 'Unknown player' })
    else record(et, team, null)
  }
  const afterPick = async (playerId) => {
    const { et, team, followUp } = picker
    setPicker(null)
    if (followUp && !playerId) return // "No assist"
    await record(et, team, playerId)
    const fu = !followUp && et.followUp && byId[et.followUp]
    if (fu) setPicker({ et: fu, team, optional: true, skipLabel: `No ${fu.label.toLowerCase()}`, followUp: true, exclude: playerId })
  }

  const lastFive = v.events.slice(0, 5)
  const undoable = v.events.find((e) => !e.undone && !CONTROL.has(e.type))
  const failed = c.queue.find((q) => q.error)
  const padTypes = t.eventTypes.filter((e) => e.group !== 'control' && e.team)
  const padGroups = ['score', 'play', 'discipline'].map((g) => padTypes.filter((e) => e.group === g)).filter((g) => g.length)

  const header = (
    <header className="sc-scorebar">
      <div className="sc-scoreline">
        <span className="sc-sb-team"><TeamBadge team={m.home} size={26} /> {m.home.short}</span>
        <span className="sc-sb-score" aria-live="polite" aria-label={`${m.home.name} ${scoreText(0)}, ${m.away.name} ${scoreText(1)}`}>
          {scoreText(0)}<span>–</span>{scoreText(1)}
        </span>
        <span className="sc-sb-team sc-sb-team--away">{m.away.short} <TeamBadge team={m.away} size={26} /></span>
      </div>
      <div className="sc-sb-meta">
        <span>{periodLabel}{cricket && v.started ? ` · Over ${overs(batting === 'home' ? 0 : 1)}` : ''}</span>
        {minute != null && v.started && !v.finished && <span className="sc-clock">{minute}′{clockRunning ? '' : ' ⏸'}</span>}
        <SyncIndicator queue={c.queue} online={c.online} retryAt={c.retryAt} now={now} />
      </div>
    </header>
  )

  return (
    <div className="sc-console">
      {header}
      {flash && <p className="sc-flash" role="status">{flash}</p>}
      {c.load.offline && <p className="sc-banner sc-banner--offline">Offline. Taps are saved on this phone and sent when the connection is back.</p>}
      {failed && (
        <div className="sc-banner sc-banner--failed" role="alert">
          <strong>Not accepted by the server:</strong> {byId[failed.body?.type]?.label ?? failed.kind} — {failed.error.message}
          <div className="sc-banner-actions">
            <button className="sc-btn sc-btn--small" onClick={c.retry}>Retry</button>
            <button className="sc-btn sc-btn--small sc-btn--ghost" onClick={() => setConfirm({ kind: 'discard', item: failed })}>Remove it</button>
          </div>
        </div>
      )}

      {v.finished ? (
        <section className="sc-panel">
          <h1>Match finished</h1>
          <p className="sc-final">{m.home.name} {v.score[0]}–{v.score[1]} {m.away.name}</p>
          <p>{c.queue.length ? 'Sending the result when the connection allows…' : '✓ Result sent. Fans have the final score.'}</p>
          <button className="sc-btn" onClick={() => onNavigate({ type: 'scorer' })}>← My matches</button>
        </section>
      ) : m.dataLevel === 'results_only' ? (
        <section className="sc-panel">
          <h1>Enter the result</h1>
          <p className="sc-muted">This match is results only: no live events, just the final score.</p>
          <div className="sc-result">
            {['home', 'away'].map((k, i) => (
              <label key={k}>
                <span>{side(k).name}</span>
                <input type="number" inputMode="numeric" min={0} max={999} value={result[i]}
                  onChange={(e) => setResult(result.map((x, j) => (j === i ? e.target.value : x)))} />
              </label>
            ))}
          </div>
          <button className="sc-btn" disabled={result.some((x) => x === '')} onClick={() => setConfirm({ kind: 'finish', score: result.map(Number) })}>
            Finish match
          </button>
        </section>
      ) : !v.started ? (
        <section className="sc-start">
          <p className="sc-muted">{m.venue}</p>
          <button className="sc-btn sc-btn--huge" onClick={() => record(byId.start, null, null)}>▶ {byId.start?.label ?? 'Start'}</button>
        </section>
      ) : v.between ? (
        <section className="sc-start">
          {nextPeriod ? (
            <button className="sc-btn sc-btn--huge" onClick={() => record(byId.period_start, null, null)}>▶ Start {nextPeriod}</button>
          ) : (
            <p className="sc-panel">The last period has ended. Check the score and finish the match.</p>
          )}
        </section>
      ) : (
        <section className={`sc-pad sc-pad--${t.pad}`} aria-label="Event pad">
          {t.pad === 'batting' ? (
            <>
              <div className="sc-batting" role="radiogroup" aria-label="Batting team">
                <span>Batting</span>
                {['home', 'away'].map((k) => (
                  <button key={k} role="radio" aria-checked={batting === k} className={batting === k ? 'is-on' : ''} onClick={() => setBatting(k)}>
                    {side(k).short}
                  </button>
                ))}
              </div>
              {padGroups.map((g, gi) => (
                <div key={gi} className="sc-pad-grid">
                  {g.map((et) => (
                    <button key={et.id} className={`sc-ev sc-ev--${et.group}${et.wicket ? ' sc-ev--wicket' : ''}`} onClick={() => tap(et, batting)}>
                      <span className="sc-ev-icon" aria-hidden="true">{et.icon}</span>
                      <span>{/^\d$/.test(et.label) ? `${et.label} run${et.label === '1' ? '' : 's'}` : et.label}</span>
                    </button>
                  ))}
                </div>
              ))}
            </>
          ) : (
            <div className="sc-split">
              {['home', 'away'].map((k) => (
                <div key={k} className="sc-col" style={{ '--team': side(k).color }}>
                  <h2><TeamBadge team={side(k)} size={22} /> {side(k).short}</h2>
                  {padTypes.map((et) => (
                    <button key={et.id} className={`sc-ev sc-ev--${et.group}`} onClick={() => tap(et, k)}>
                      <span className="sc-ev-icon" aria-hidden="true">{et.icon}</span>
                      <span>{et.label}</span>
                    </button>
                  ))}
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      <section className="sc-events" aria-labelledby="ev-h">
        <h2 id="ev-h" className="sc-h2">Last events</h2>
        {lastFive.length ? (
          <ol>
            {lastFive.map((e) => {
              const et = byId[e.type]
              return (
                <li key={`${e.deviceId}:${e.clientSeq}`} className={e.undone ? 'is-undone' : ''}>
                  <span className="sc-ev-min">{e.minute != null ? `${e.minute}′` : ''}</span>
                  <span aria-hidden="true">{et?.icon}</span>
                  <span className="sc-ev-text">
                    <strong>{et?.label ?? e.type}</strong>
                    {e.team && ` · ${side(e.team).short}`}
                    {e.playerId && ` · ${e.playerLabel ?? playerLabel(e.team, e.playerId)}`}
                    {e.undone && ' · taken back'}
                  </span>
                  {e.state !== 'synced' && <span className={`sc-ev-state sc-ev-state--${e.state}`}>{e.state === 'failed' ? 'failed' : 'queued'}</span>}
                  {undoable && e === undoable && !v.finished && (
                    <button className="sc-undo" onClick={() => setConfirm({ kind: 'undo', event: e })}>Undo</button>
                  )}
                </li>
              )
            })}
          </ol>
        ) : (
          <p className="sc-empty">No events yet.</p>
        )}
      </section>

      {!v.finished && m.dataLevel !== 'results_only' && (
        <footer className="sc-footer">
          <button className="sc-btn sc-btn--ghost" disabled={!v.started || v.between} onClick={() => record(byId.period_end, null, null)}>
            ⏸ End {v.started ? t.periods[v.periodIndex] : 'period'}
          </button>
          <button className="sc-btn sc-btn--danger" disabled={!v.started} onClick={() => setConfirm({ kind: 'finish', score: v.score })}>
            ■ Finish match
          </button>
        </footer>
      )}

      {picker && (
        <PlayerPicker title={picker.et.playerPrompt ?? picker.et.label} team={picker.team} rosters={rosters} recent={recent}
          optional={picker.optional} skipLabel={picker.skipLabel} exclude={picker.exclude}
          onPick={afterPick} onSkip={() => afterPick(null)} onCancel={() => setPicker(null)} />
      )}

      <Confirm open={confirm?.kind === 'undo'} title="Undo the last event?" confirmLabel="Undo" danger
        onCancel={() => setConfirm(null)}
        onConfirm={() => { c.undo(confirm.event); setConfirm(null); say('↩ Taken back') }}>
        {confirm?.kind === 'undo' && (
          <p>{byId[confirm.event.type]?.label}{confirm.event.team ? ` · ${side(confirm.event.team).name}` : ''}
            {confirm.event.playerId ? ` · ${confirm.event.playerLabel ?? playerLabel(confirm.event.team, confirm.event.playerId)}` : ''}</p>
        )}
      </Confirm>
      <Confirm open={confirm?.kind === 'finish'} title="Finish the match?" confirmLabel="Finish match" danger
        onCancel={() => setConfirm(null)}
        onConfirm={() => { c.finish(confirm.score); setConfirm(null) }}>
        {confirm?.kind === 'finish' && (
          <>
            <p className="sc-final">{m.home.name} {confirm.score[0]}–{confirm.score[1]} {m.away.name}</p>
            <p>Fans get this as the final result and the match report is written from it. This can’t be undone here.</p>
          </>
        )}
      </Confirm>
      <Confirm open={confirm?.kind === 'discard'} title="Remove the refused event?" confirmLabel="Remove" danger
        onCancel={() => setConfirm(null)}
        onConfirm={() => { c.discard(confirm.item); setConfirm(null) }}>
        <p>The server didn’t accept it, so it isn’t on the fans’ feed. Removing it lets the events after it be sent.</p>
      </Confirm>
    </div>
  )
}
