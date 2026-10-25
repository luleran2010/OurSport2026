// Dates and times for OurSport. Every game is in Finland, so times are always shown in Finnish time
// (Europe/Helsinki), whatever time zone the viewer's device is in.

export const TIME_ZONE = 'Europe/Helsinki'
const DAY = 24 * 60 * 60 * 1000

/** Intl options with the app's time zone. */
const tz = (options) => ({ timeZone: TIME_ZONE, ...options })

/** Calendar day in Helsinki as a number of days since 1970 (for "today / tomorrow" maths). */
function dayNumber(ts) {
  const [y, m, d] = new Intl.DateTimeFormat('en-CA', tz({ year: 'numeric', month: '2-digit', day: '2-digit' }))
    .format(new Date(ts))
    .split('-')
    .map(Number)
  return Math.round(Date.UTC(y, m - 1, d) / DAY)
}

export function timeAgo(ts, now = Date.now()) {
  const s = Math.max(0, Math.round((now - ts) / 1000))
  if (s < 45) return 'just now'
  const m = Math.round(s / 60)
  if (m < 60) return `${m} min ago`
  const h = Math.round(m / 60)
  if (h < 24) return `${h} h ago`
  return `${Math.round(h / 24)} d ago`
}

/** "18:30" */
export function clockTime(ts, locale = []) {
  return new Date(ts).toLocaleTimeString(locale, tz({ hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }))
}

/** Short countdown for games starting within the hour, otherwise empty. */
export function startsIn(ts, now = Date.now()) {
  const m = Math.round((ts - now) / 60000)
  if (m <= 0) return 'Starting'
  if (m < 60) return `in ${m} min`
  return ''
}

/** "Today", "Tomorrow", "Yesterday" or "Saturday, 31 Oct". */
export function dayLabel(ts, now = Date.now()) {
  const diff = dayNumber(ts) - dayNumber(now)
  if (diff === 0) return 'Today'
  if (diff === 1) return 'Tomorrow'
  if (diff === -1) return 'Yesterday'
  return new Date(ts).toLocaleDateString([], tz({ weekday: 'long', day: 'numeric', month: 'short' }))
}

/** "24 Oct 2026" (short) or "24 October 2026" (long). */
export function formatDate(ts, { long = false, locale = [] } = {}) {
  return new Date(ts).toLocaleDateString(locale, tz({ day: 'numeric', month: long ? 'long' : 'short', year: 'numeric' }))
}

/** "Saturday, 24 October" — the home feed's date line. */
export function formatWeekday(ts, locale = []) {
  return new Date(ts).toLocaleDateString(locale, tz({ weekday: 'long', day: 'numeric', month: 'long' }))
}

/** Full date and time, e.g. for tooltips. */
export function formatDateTime(ts, locale = []) {
  return new Date(ts).toLocaleString(locale, tz({ dateStyle: 'medium', timeStyle: 'short', hourCycle: 'h23' }))
}

/** "Fri 23 – Sun 25 Oct" (or across months: "Fri 30 Oct – Sun 1 Nov"). */
export function formatDateRange(start, end) {
  const parts = (ts) => {
    const p = Object.fromEntries(
      new Intl.DateTimeFormat('en-GB', tz({ weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' }))
        .formatToParts(new Date(ts))
        .map((x) => [x.type, x.value]),
    )
    return p
  }
  const s = parts(start)
  const e = parts(end)
  const day = (p, withMonth) => `${p.weekday} ${p.day}${withMonth ? ` ${p.month}` : ''}`
  if (dayNumber(start) === dayNumber(end)) return day(s, true)
  const sameMonth = s.month === e.month && s.year === e.year
  return `${day(s, !sameMonth)} – ${day(e, true)}`
}

/** A calendar date from the API ("2026-11-01", no time of day): "1 Nov 2026", the same in every time zone. */
export function formatDay(isoDate, { long = false, locale = [] } = {}) {
  const [y, m, d] = isoDate.split('-').map(Number)
  return formatDate(Date.UTC(y, m - 1, d, 12), { long, locale })
}

/** "YYYY-MM-DDTHH:MM" in Finnish time, for <input type="datetime-local">. */
export function toZonedInput(ts) {
  const p = Object.fromEntries(
    new Intl.DateTimeFormat('en-CA', tz({ year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }))
      .formatToParts(new Date(ts))
      .map((x) => [x.type, x.value]),
  )
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`
}

/** Epoch ms of a Finnish wall-clock time "YYYY-MM-DDTHH:MM" (the inverse of toZonedInput). */
export function fromZonedInput(value) {
  const asUtc = (s) => {
    const [d, t] = s.split('T')
    const [y, m, dd] = d.split('-').map(Number)
    const [h, mi] = t.split(':').map(Number)
    return Date.UTC(y, m - 1, dd, h, mi)
  }
  const wall = asUtc(value)
  const offset = (ts) => asUtc(toZonedInput(ts)) - ts
  const first = wall - offset(wall)
  return wall - offset(first)
}
