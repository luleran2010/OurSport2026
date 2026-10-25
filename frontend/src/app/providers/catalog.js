import { createContext, useContext } from 'react'

// Reference data loaded once from the backend (see useCatalogData).
export const CatalogContext = createContext({ sports: [], teams: {}, clubs: {}, tournaments: {}, regions: [], ageGroups: [], types: [] })

export function useCatalog() {
  const { sports, teams, clubs = {}, tournaments = {}, regions = [], ageGroups = [], types = [], reload = () => {} } = useContext(CatalogContext)
  const sportOf = (id) => sports.find((s) => s.id === id)
  return {
    sports,
    teams,
    clubs,
    tournaments,
    regions,
    ageGroups,
    types,
    reload,
    sportIcon: (id) => sportOf(id)?.icon ?? '',
    sportLabel: (id) => sportOf(id)?.label ?? id,
    regionLabel: (id) => regions.find((r) => r.id === id)?.label ?? id,
    ageLabel: (id) => ageGroups.find((a) => a.id === id)?.label ?? id,
  }
}
