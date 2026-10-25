import { createContext, useContext } from 'react'

// { me, signIn (demo), signOut, replaceMe, authenticated, requestLogin } — see hooks/useMe and App.
export const MeContext = createContext({
  me: null,
  signIn: async () => {},
  signOut: async () => {},
  replaceMe: () => {},
  authenticated: async () => {},
  requestLogin: () => {},
})

export const useMeContext = () => useContext(MeContext)
