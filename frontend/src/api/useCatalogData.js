import { useCallback, useEffect, useState } from 'react'
import { api } from './client'
import { readSaved, save } from './offlineCache'

// Reference data loaded once: sports, teams, clubs and the Explore filter options.
// `reload()` fetches it again after reference data changes.
export function useCatalogData() {
  const [state, setState] = useState({
    status: 'loading', sports: [], teams: {}, clubs: {}, tournaments: {}, regions: [], ageGroups: [], types: [], error: null,
  })

  const [version, setVersion] = useState(0)
  const reload = useCallback(() => setVersion((v) => v + 1), [])

  useEffect(() => {
    let cancelled = false
    Promise.all([api.sports(), api.teams(), api.searchFilters(), api.clubs(), api.tournaments()])
      .then(([sports, teamList, filters, clubList, tournamentList]) => {
        if (cancelled) return
        const teams = Object.fromEntries(teamList.map((t) => [t.id, t]))
        const clubs = Object.fromEntries(clubList.map((c) => [c.id, c]))
        const tournaments = Object.fromEntries(tournamentList.map((t) => [t.id, t]))
        const next = {
          status: 'ready', sports, teams, clubs, tournaments,
          regions: filters.regions, ageGroups: filters.ageGroups, types: filters.types, error: null,
        }
        save('catalog', next)
        setState(next)
      })
      .catch((error) => {
        if (cancelled) return
        const saved = error.status ? null : readSaved('catalog') // offline: the copy from the last visit
        setState((s) => (saved ? { ...saved, offline: true } : { ...s, status: 'error', error }))
      })
    return () => {
      cancelled = true
    }
  }, [version])

  return { ...state, reload }
}
