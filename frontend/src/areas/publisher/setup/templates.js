// Ready-made documents for the Documents step: a team list and a rulebook the backend reads like
// an organiser's own (one team per line "Team (Club)", the rules in plain sentences). Team and
// club names are made up. Dates, age group and sport come from the event.

const CLUBS = [
  ['Northside Rovers', 'Northside SC'], ['Lakeview United', 'Lakeview FC'], ['Harbour Athletic', 'Harbour AC'],
  ['Pinewood Wanderers', 'Pinewood SC'], ['Riverside Stars', 'Riverside FC'], ['Hilltop Rangers', 'Hilltop SC'],
  ['Meadow City', 'Meadow City FC'], ['Old Town Albion', 'Old Town FC'], ['Eastfield Eagles', 'Eastfield SC'],
  ['Westbrook Comets', 'Westbrook FC'], ['Stonebridge Lions', 'Stonebridge SC'], ['Bayside Falcons', 'Bayside FC'],
  ['Kingsgate Tigers', 'Kingsgate SC'], ['Mill Lane Rockets', 'Mill Lane FC'], ['Forest Park Owls', 'Forest Park SC'],
  ['Southbank Sharks', 'Southbank FC'],
]

export const TEMPLATES = [
  {
    id: 'one_day_cup', title: 'One-day cup', teams: 8, groups: 2, through: 2, knockout: 'semi-finals and a final',
    pitches: 2, periods: '2 × 15 minutes', halfTime: 5,
    text: '8 teams, 2 groups of 4, then semi-finals and a final. One day, 2 pitches.',
  },
  {
    id: 'league_day', title: 'League day', teams: 6, groups: 1, through: 0,
    pitches: 2, periods: '2 × 12 minutes', halfTime: 3,
    text: '6 teams, everyone plays everyone once; the table decides. One day, 2 pitches.',
  },
  {
    id: 'weekend_cup', title: 'Weekend cup', teams: 16, groups: 4, through: 2, knockout: 'quarter-finals, semi-finals and a final',
    pitches: 4, periods: '2 × 20 minutes', halfTime: 5,
    text: '16 teams, 4 groups of 4, then quarter-finals. Best over 2–3 days, 4 pitches.',
  },
]

const ageLabel = (age) => (age && age !== 'adult' ? ` ${age.toUpperCase()}` : '')

function playingDays(t) {
  if (!t.starts_on) return []
  const days = []
  const last = Date.parse(`${t.ends_on ?? t.starts_on}T00:00:00Z`)
  for (let d = Date.parse(`${t.starts_on}T00:00:00Z`); d <= last && days.length < 7; d += 86400000) {
    days.push(new Date(d).toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' }))
  }
  return days
}

/** The team list of a template: "Team (Club)", one per line. */
export function teamList(template, tournament) {
  return CLUBS.slice(0, template.teams).map(([team, club]) => `${team}${ageLabel(tournament.age_group)} (${club})`).join('\n')
}

/** The rulebook of a template, written for the event's dates. */
export function rulebook(template, tournament) {
  const { teams, groups, through, pitches } = template
  const sport = tournament.sport === 'futsal' ? 'futsal' : 'football'
  const days = playingDays(tournament)
  const lines = [`${tournament.name} — tournament rules`, '']
  if (groups > 1) {
    lines.push(
      `Format: ${teams} teams are drawn into ${groups} groups of ${teams / groups}. Every team plays every other team in its group once.`,
      `The top ${through} of each group go through to the knockout stage: ${template.knockout}.`,
      'Knockout matches that end level are decided by a penalty shoot-out.',
    )
  } else {
    lines.push(`Format: one league of ${teams} teams. Every team plays every other team once. The final table decides the winner; there is no knockout stage.`)
  }
  lines.push(
    '',
    'Points: 3 for a win, 1 for a draw, 0 for a loss.',
    'Teams level on points are separated by: the result between them, then goal difference, then goals scored, then drawing of lots.',
    '',
    `Matches: ${template.periods} with a ${template.halfTime}-minute half-time, played under ${sport} rules.`,
    '',
  )
  if (days.length) lines.push(`Playing days: ${days.join(', ')}. Play runs from 09:00 to 18:00 each day.`)
  lines.push(`Pitches: ${Array.from({ length: pitches }, (_, i) => `Pitch ${i + 1}`).join(', ')}. Teams get at least 30 minutes of rest between matches.`)
  return lines.join('\n')
}
