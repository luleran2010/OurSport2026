export default function TeamBadge({ team, size = 36 }) {
  return (
    <span
      className="team-badge"
      style={{ '--team': team.color, width: size, height: size, fontSize: size * 0.32 }}
      aria-hidden="true"
    >
      {team.short}
    </span>
  )
}
