import { useEffect, useRef } from 'react'
import { useCatalog } from '../../providers/catalog'

/** Shown when a guest taps Follow: following is for signed-in members. */
export default function SignInPrompt({ target, onSignIn, onGoTo, onClose }) {
  const ref = useRef(null)
  const { clubs, teams, tournaments } = useCatalog()
  const name =
    target && ({ club: clubs, team: teams, tournament: tournaments }[target.kind]?.[target.id]?.name ?? 'this')

  useEffect(() => {
    const d = ref.current
    if (target && d && !d.open) d.showModal()
    if (!target && d?.open) d.close()
  }, [target])

  return (
    <dialog
      ref={ref}
      className="modal"
      // Only a real dismissal (Esc) cancels; closing because the fan went to log in keeps the follow pending.
      onClose={() => target && onClose()}
      aria-labelledby="signin-h"
    >
      <div className="modal-body">
        <h2 id="signin-h">Log in to follow</h2>
        <p className="page-sub">
          Following {name} puts its games, results and news on your home page, with alerts you choose.
          Following is for members — it’s free.
        </p>
        <div className="modal-actions">
          <button className="btn btn--ghost" onClick={onClose}>Not now</button>
          <button className="btn btn--ghost" onClick={() => onGoTo('signup')}>Create account</button>
          <button className="btn btn--accent" onClick={() => onGoTo('login')} autoFocus>Log in</button>
        </div>
        <p className="demo-line">
          Just looking?{' '}
          <button className="link-btn link-btn--accent" onClick={() => onSignIn('premium')}>Try the demo account</button>
        </p>
      </div>
    </dialog>
  )
}
