// Number and text formatting shared by all areas.

/** 1 241 / 1,241 depending on the viewer's locale. */
export const formatNumber = (n, locale = []) => Number(n).toLocaleString(locale)

/** "1 player" / "3 players" */
export const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`
