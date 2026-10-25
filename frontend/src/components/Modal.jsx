import { useEffect, useRef } from 'react'

/** Native <dialog> as a modal, opened and closed by the `open` prop. */
export default function Modal({ open, onClose, labelledBy, wide = false, children }) {
  const ref = useRef(null)
  useEffect(() => {
    const d = ref.current
    if (open && !d.open) d.showModal()
    if (!open && d.open) d.close()
  }, [open])
  return (
    <dialog ref={ref} className={`modal${wide ? ' modal--wide' : ''}`} onClose={onClose} aria-labelledby={labelledBy}>
      {open && children}
    </dialog>
  )
}
