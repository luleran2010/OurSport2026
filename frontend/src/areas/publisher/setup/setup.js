import { useState } from 'react'

// Shared helpers of the setup wizard (automatic tournament setup, backend/docs/12-tournament-setup.md).

export const STATUS = {
  intake: { label: 'Collecting documents', tone: 'muted' },
  extracting: { label: 'Reading documents', tone: 'info' },
  needs_answers: { label: 'Questions to answer', tone: 'warn' },
  drawing: { label: 'Drawing', tone: 'info' },
  ready: { label: 'Ready to publish', tone: 'info' },
  published: { label: 'Published', tone: 'done' },
  failed: { label: 'Needs attention', tone: 'warn' },
}

export const STAGE = {
  group: 'Group', round_of_16: 'Round of 16', quarter_final: 'Quarter-final', semi_final: 'Semi-final',
  third_place: 'Third place', final: 'Final',
}

const TIEBREAKER = {
  points: 'points', head_to_head_points: 'points between the tied teams', head_to_head_diff: 'goal difference between them',
  head_to_head_for: 'goals scored between them', score_diff: 'goal difference', score_for: 'goals scored',
  wins: 'wins', fair_play: 'fair play', draw_lots: 'drawing of lots', rating: 'rating',
}

export const tiebreakers = (list = []) => list.map((t) => TIEBREAKER[t] ?? t.replaceAll('_', ' ')).join(' → ')

/** "group:A:1" → "Winner Group A", "winner:SF1" → "Winner SF1". */
export function sourceLabel(source) {
  if (!source) return 'To be decided'
  const [kind, a, b] = source.split(':')
  if (kind === 'group') return `${b === '1' ? 'Winner' : b === '2' ? 'Runner-up' : `${b}.`} Group ${a}`
  if (kind === 'winner') return `Winner ${a}`
  if (kind === 'loser') return `Loser ${a}`
  if (kind === 'best_rest') return `Best of the rest (${a})`
  return source
}

export const teamName = (setup, key) => setup.draft?.draft.teams.find((t) => t.key === key)?.name ?? key

/** Busy/error state for one action; a stale draft (someone else edited) reloads the setup. */
export function useAction(onSetup, reload) {
  const [state, setState] = useState({ busy: false, error: '' })
  const run = async (fn, okText = '') => {
    setState({ busy: true, error: '' })
    try {
      const result = await fn()
      if (result?.id && result.status) onSetup(result)
      setState({ busy: false, error: '', ok: okText })
      return result
    } catch (err) {
      if (err.code === 'stale_version') {
        await reload()
        setState({ busy: false, error: 'The draft changed in the meantime (another tab?). It has been reloaded — please check and try again.' })
      } else {
        setState({ busy: false, error: err.message || 'Something went wrong.', code: err.code })
      }
      return null
    }
  }
  return { ...state, run }
}
