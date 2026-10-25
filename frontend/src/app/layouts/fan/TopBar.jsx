import { useState } from 'react'

export default function TopBar({ onMenu, onSearch, showSearch = true, unread = 0, onBell }) {
  const [text, setText] = useState('')

  const submit = (e) => {
    e.preventDefault()
    onSearch(text.trim())
    setText('')
  }

  return (
    <header className="topbar">
      <button className="icon-btn menu-btn" aria-label="Open menu" onClick={onMenu}>
        <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
          <path fill="currentColor" d="M3 6h18v2H3zm0 5h18v2H3zm0 5h18v2H3z" />
        </svg>
      </button>
      <span className="topbar-brand brand-name">OurSport<span className="brand-ai"> AI</span></span>
      {showSearch ? (
        <form className="search" role="search" onSubmit={submit}>
          <label className="visually-hidden" htmlFor="topbar-search">Search clubs, teams, events and players</label>
          <input
            id="topbar-search"
            type="search"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Search clubs, teams, events, players"
          />
        </form>
      ) : (
        <span className="search" aria-hidden="true" />
      )}
      <button className="icon-btn" aria-label={unread ? `Notifications, ${unread} unread` : 'Notifications'} onClick={onBell}>
        <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
          <path fill="currentColor" d="M12 22a2.5 2.5 0 0 0 2.45-2h-4.9A2.5 2.5 0 0 0 12 22Zm7-6V11a7 7 0 0 0-5.5-6.84V3a1.5 1.5 0 0 0-3 0v1.16A7 7 0 0 0 5 11v5l-2 2v1h18v-1Z" />
        </svg>
        {unread > 0 && <span className="bell-count">{unread > 99 ? '99+' : unread}</span>}
      </button>
    </header>
  )
}
