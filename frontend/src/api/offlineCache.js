// Last good copy of app-wide data (account, catalog) on this device, for pages that must open offline
// (the scorer area). Storage can be blocked or full: every call is wrapped and failing is harmless.
const key = (name) => `lp-cache:${name}`

export function save(name, value) {
  try {
    localStorage.setItem(key(name), JSON.stringify(value))
  } catch {
    /* ignore */
  }
}

export function readSaved(name) {
  try {
    const raw = localStorage.getItem(key(name))
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}
