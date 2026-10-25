import { useMeContext } from '../../app/providers/me'

const COPY = {
  profile: { title: 'Profile', text: 'Your fan profile: name, photo, home area and favourite sports.' },
  notifications: { title: 'Notifications', text: 'Choose alerts for your teams: game start, goals and final scores.' },
  settings: { title: 'Settings', text: 'Language, theme, data usage and privacy settings.' },
}

export default function AccountView({ kind }) {
  const { me, requestLogin } = useMeContext()
  const c = COPY[kind]
  return (
    <>
      <div className="page-head">
        <h1>{c.title}</h1>
        <p className="page-sub">{c.text}</p>
      </div>
      <div className="placeholder">
        {me?.signedIn ? (
          <>
            <p>Signed in as <strong>{me.name}</strong>{me.premium && <> · ★ {me.premium.plan} via {me.premium.viaClubName}</>}.</p>
            <p>More {c.title.toLowerCase()} options are coming soon.</p>
          </>
        ) : (
          <>
            <p>Sign in to manage your {c.title.toLowerCase()}.</p>
            <button className="btn btn--accent" onClick={() => requestLogin()}>Log in</button>
          </>
        )}
      </div>
    </>
  )
}
