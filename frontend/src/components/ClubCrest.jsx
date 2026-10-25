// Club logo: the uploaded logo when there is one, otherwise a shield crest
// drawn from the club colour and short name.
export default function ClubCrest({ club, size = 40 }) {
  if (club.logoUrl) {
    return <img className="club-logo" src={club.logoUrl} alt="" width={size} height={size} />
  }
  return (
    <svg className="club-crest" width={size} height={size * 1.15} viewBox="0 0 40 46" aria-hidden="true">
      <path d="M20 1.5 37.5 7v15.5C37.5 34 29.5 41 20 44.5 10.5 41 2.5 34 2.5 22.5V7Z" fill={club.color} stroke="rgb(255 255 255 / .35)" strokeWidth="1.5" />
      <path d="M20 1.5 37.5 7v15.5C37.5 34 29.5 41 20 44.5Z" fill="rgb(0 0 0 / .18)" />
      <text x="20" y="27" textAnchor="middle" fontFamily="'Barlow Condensed', 'Arial Narrow', sans-serif" fontWeight="700" fontSize={club.short.length > 3 ? 10.5 : 13} fill="#fff" letterSpacing=".5">
        {club.short}
      </text>
    </svg>
  )
}
