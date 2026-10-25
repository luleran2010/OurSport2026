import { useState } from 'react'

/** Native share sheet when available, otherwise copies "text + link" to the clipboard. */
export default function ShareButton({ title, text, label = '↗ Share', copiedLabel = '✓ Link copied' }) {
  const [copied, setCopied] = useState(false)
  const share = async () => {
    const url = window.location.href
    try {
      if (navigator.share) {
        await navigator.share({ title, text, url })
        return
      }
      await navigator.clipboard.writeText(`${text} ${url}`)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      /* share sheet dismissed or clipboard blocked */
    }
  }
  return <button className="btn btn--ghost btn--sm" onClick={share}>{copied ? copiedLabel : label}</button>
}
