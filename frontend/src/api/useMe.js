import { useEffect, useState } from 'react'
import { api } from './client'
import { readSaved, save } from './offlineCache'

// The current fan (a cookie session on the backend): sign-in state, Premium
// and follows. Follow changes are applied optimistically, then confirmed.
export function useMe() {
  const [state, setState] = useState({ status: 'loading', me: null })
  // Guests can't follow: a Follow tap opens a sign-in prompt and is completed after signing in.
  const [pendingFollow, setPendingFollow] = useState(null) // { kind, id, deferred? } | null

  const setMe = (me) => {
    save('me', me) // the scorer pages open offline with the last known account
    setState({ status: 'ready', me })
  }
  const resync = () => api.me().then(setMe).catch(() => {})

  useEffect(() => {
    api
      .me()
      .then(setMe)
      .catch((error) => {
        // network down (no HTTP answer): carry on with the account saved on this device
        const saved = error.status ? null : readSaved('me')
        setState(saved ? { status: 'ready', me: saved, offline: true } : { status: 'error', me: null, error })
      })
  }, [])

  const { me } = state
  const teams = me?.follows.teams ?? []
  const clubs = me?.follows.clubs ?? []
  const tournaments = me?.follows.tournaments ?? []

  const toggleFollow = (kind, id) => {
    if (!me?.signedIn) {
      setPendingFollow({ kind, id })
      return
    }
    const key = { club: 'clubs', team: 'teams', tournament: 'tournaments' }[kind]
    const on = (me?.follows[key] ?? []).includes(id)
    const current = (f) => f[key] ?? []
    setState((s) => ({
      ...s,
      me: {
        ...s.me,
        follows: { ...s.me.follows, [key]: on ? current(s.me.follows).filter((x) => x !== id) : [...current(s.me.follows), id] },
      },
    }))
    ;(on ? api.unfollow(kind, id) : api.follow(kind, id)).then(setMe).catch(resync)
  }

  return {
    status: state.status,
    me,
    signIn: (plan) => api.demoLogin(plan).then(setMe),
    pendingFollow: pendingFollow?.deferred ? null : pendingFollow, // the prompt shows only while not deferred
    intendedFollow: pendingFollow, // sent with a sign-up, so the new account follows it
    cancelPendingFollow: () => setPendingFollow(null),
    deferPendingFollow: () => setPendingFollow((p) => p && { ...p, deferred: true }),
    /** After log-in / sign-up / reset: store the fan and finish a follow they asked for as a guest. */
    authenticated: async (signedInMe) => {
      const target = pendingFollow
      setPendingFollow(null)
      let next = signedInMe
      const key = target && { club: 'clubs', team: 'teams', tournament: 'tournaments' }[target.kind]
      if (target && !next.follows[key].includes(target.id)) {
        next = await api.follow(target.kind, target.id).catch(() => next)
      }
      setMe(next)
    },
    /** Sign in from the prompt, then complete the follow the guest asked for. */
    signInAndFollow: async (plan) => {
      const target = pendingFollow
      setPendingFollow(null)
      let me = await api.demoLogin(plan)
      const key = target && { club: 'clubs', team: 'teams', tournament: 'tournaments' }[target.kind]
      if (target && !me.follows[key].includes(target.id)) me = await api.follow(target.kind, target.id)
      setMe(me)
    },
    signOut: () => api.logout().then(setMe),
    replaceMe: setMe, // after PATCH /me, redeem-code, delete
    follow: {
      followed: teams,
      clubs,
      isFollowed: (id) => teams.includes(id),
      toggle: (id) => toggleFollow('team', id),
      isClubFollowed: (id) => clubs.includes(id),
      toggleClub: (id) => toggleFollow('club', id),
      tournaments,
      isTournamentFollowed: (id) => tournaments.includes(id),
      toggleTournament: (id) => toggleFollow('tournament', id),
    },
  }
}
