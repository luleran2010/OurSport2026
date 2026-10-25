import { CatalogContext } from './providers/catalog'
import { MeContext } from './providers/me'

/** App-wide data every area reads: the catalog (sports, teams, clubs…) and the signed-in user. */
export default function AppProviders({ catalog, meState, requestLogin, children }) {
  return (
    <CatalogContext value={catalog}>
      <MeContext
        value={{
          me: meState.me,
          signIn: meState.signIn,
          signOut: meState.signOut,
          replaceMe: meState.replaceMe,
          authenticated: meState.authenticated,
          pendingFollow: meState.intendedFollow,
          requestLogin,
        }}
      >
        {children}
      </MeContext>
    </CatalogContext>
  )
}
