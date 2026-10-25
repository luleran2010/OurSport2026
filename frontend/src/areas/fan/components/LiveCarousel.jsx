import { useEffect, useRef, useState } from 'react'
import TeamBadge from '../../../components/TeamBadge'
import { useCatalog } from '../../../app/providers/catalog'

const AUTOPLAY_MS = 6000
const SWIPE_PX = 50

// Shortest signed distance from the active slide, so the carousel loops.
function offsetOf(i, active, n) {
  let o = i - active
  if (n > 2) {
    if (o > n / 2) o -= n
    if (o < -n / 2) o += n
  }
  return o
}

export default function LiveCarousel({ matches, onWatch }) {
  const { sportIcon } = useCatalog()
  const live = matches.filter((m) => m.status === 'live')
  const n = live.length
  const [index, setIndex] = useState(0)
  const [drag, setDrag] = useState(0)
  const [paused, setPaused] = useState(false)
  const pointer = useRef(null)
  const justDragged = useRef(false)

  const active = n ? ((index % n) + n) % n : 0
  const go = (d) => setIndex((i) => i + d)

  useEffect(() => {
    if (paused || n < 2) return
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
    const id = setInterval(() => setIndex((i) => i + 1), AUTOPLAY_MS)
    return () => clearInterval(id)
  }, [paused, n])

  if (!n) {
    return <p className="empty">No games in progress right now — see “Today &amp; next” below.</p>
  }

  const onPointerDown = (e) => {
    if (e.button !== 0) return
    pointer.current = { x: e.clientX, dx: 0, moved: false }
  }
  const onPointerMove = (e) => {
    const p = pointer.current
    if (!p) return
    p.dx = e.clientX - p.x
    if (!p.moved) {
      if (Math.abs(p.dx) < 8) return
      p.moved = true
      e.currentTarget.setPointerCapture?.(e.pointerId)
    }
    setDrag(p.dx)
  }
  const onPointerEnd = () => {
    const p = pointer.current
    pointer.current = null
    if (!p?.moved) return
    if (p.dx <= -SWIPE_PX) go(1)
    else if (p.dx >= SWIPE_PX) go(-1)
    setDrag(0)
    justDragged.current = true
    setTimeout(() => (justDragged.current = false), 0)
  }

  return (
    <div
      className="carousel"
      aria-roledescription="carousel"
      aria-label="Live games"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
    >
      <div className="carousel-viewport">
        <div
          className={`carousel-stage${drag ? ' is-dragging' : ''}`}
          tabIndex={0}
          aria-label="Use left and right arrow keys to switch games"
          onKeyDown={(e) => {
            if (e.key === 'ArrowLeft') go(-1)
            if (e.key === 'ArrowRight') go(1)
          }}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerEnd}
          onPointerCancel={onPointerEnd}
          onClickCapture={(e) => {
            if (justDragged.current) {
              e.stopPropagation()
              e.preventDefault()
            }
          }}
        >
          {live.map((m, i) => {
            const o = offsetOf(i, active, n)
            const isActive = o === 0
            return (
              <article
                key={m.id}
                className={`slide${isActive ? ' is-active' : ''}`}
                role="group"
                aria-roledescription="slide"
                aria-label={`${i + 1} of ${n}: ${m.home.name} vs ${m.away.name}`}
                aria-hidden={!isActive || undefined}
                onClick={isActive ? undefined : () => setIndex(index + o)}
                style={{
                  '--o': o,
                  '--drag': `${drag}px`,
                  '--s': isActive ? 1 : 0.86,
                  zIndex: 10 - Math.abs(o),
                  opacity: Math.abs(o) > 1 ? 0 : 1,
                  pointerEvents: Math.abs(o) > 1 ? 'none' : undefined,
                }}
              >
                <div className="slide-media" style={{ '--home': m.home.color, '--away': m.away.color }}>
                  <div className="slide-top">
                    <span className="live-pill"><span className="pulse" />LIVE</span>
                    <span className="slide-chip">{[m.clock != null && `${m.clock}′`, m.period].filter(Boolean).join(' · ')}</span>
                  </div>
                  <div className="slide-score">
                    <TeamBadge team={m.home} size={52} />
                    <span className={`slide-nums${m.flash != null ? ' is-flash' : ''}`}>
                      {m.score[0]}<i>–</i>{m.score[1]}
                    </span>
                    <TeamBadge team={m.away} size={52} />
                  </div>
                  <span className="slide-sport" aria-hidden="true">{sportIcon(m.sport)}</span>
                  <span className="slide-chip slide-viewers">👁 {m.viewers} watching</span>
                </div>

                <div className="slide-body">
                  <h3 className="slide-title">
                    {m.home.name} <span>vs</span> {m.away.name}
                  </h3>
                  <p className="slide-league">{m.league}</p>
                  {m.lastEvent && <p className="slide-text">{m.lastEvent}</p>}
                  <p className="slide-venue">📍 {m.venue}</p>
                </div>

                <button className="slide-cta" tabIndex={isActive ? 0 : -1} onClick={() => onWatch(m)}>
                  WATCH LIVE
                </button>
              </article>
            )
          })}
        </div>

        {n > 1 && (
          <>
            <button className="carousel-arrow carousel-arrow--prev" aria-label="Previous game" onClick={() => go(-1)}>‹</button>
            <button className="carousel-arrow carousel-arrow--next" aria-label="Next game" onClick={() => go(1)}>›</button>
          </>
        )}
      </div>

      {n > 1 && (
        <div className="carousel-dots" role="tablist" aria-label="Choose game">
          {live.map((m, i) => (
            <button
              key={m.id}
              role="tab"
              aria-selected={i === active}
              aria-label={`${m.home.short} vs ${m.away.short}`}
              onClick={() => setIndex(index + offsetOf(i, active, n))}
            />
          ))}
        </div>
      )}
    </div>
  )
}
