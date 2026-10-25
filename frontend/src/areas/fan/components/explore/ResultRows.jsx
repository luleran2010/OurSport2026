import TeamBadge from '../../../../components/TeamBadge'
import ClubCrest from '../../../../components/ClubCrest'
import { useCatalog } from '../../../../app/providers/catalog'

export function FollowButton({ on, onToggle, label, children }) {
  return (
    <button
      className={`btn btn--sm ${on ? 'btn--ghost' : 'btn--accent'}`}
      aria-pressed={on}
      aria-label={`${on ? 'Unfollow' : 'Follow'} ${label}`}
      onClick={onToggle}
    >
      {on ? '✓ Following' : children ?? 'Follow'}
    </button>
  )
}

export function ClubRow({ club, follow, onNavigate, distanceKm }) {
  const { sportIcon, regionLabel } = useCatalog()
  const on = follow.isClubFollowed(club.id)
  const n = club.teamIds.length
  return (
    <li className="result-row">
      <button className="rr-main" onClick={() => onNavigate({ type: 'club', clubId: club.id })}>
        <ClubCrest club={club} size={36} />
        <span className="rr-text">
          <span className="rr-title">{club.name}</span>
          <span className="rr-sub">
            {club.city} · {regionLabel(club.region)} · {club.sports.map(sportIcon).join(' ')} {n} team{n === 1 ? '' : 's'}
          </span>
        </span>
        {distanceKm != null && <span className="rr-dist">{distanceKm} km</span>}
      </button>
      <FollowButton on={on} label={club.name} onToggle={() => follow.toggleClub(club.id)}>
        Follow club
      </FollowButton>
    </li>
  )
}

export function TeamRow({ team, follow, onNavigate }) {
  const { sportIcon, ageLabel, regionLabel } = useCatalog()
  return (
    <li className="result-row">
      <button className="rr-main" onClick={() => onNavigate({ type: 'team', teamId: team.id })}>
        <TeamBadge team={team} size={40} />
        <span className="rr-text">
          <span className="rr-title">{team.name}</span>
          <span className="rr-sub">
            {sportIcon(team.sport)} {team.league} · {ageLabel(team.ageGroup)} · {regionLabel(team.region)}
          </span>
        </span>
      </button>
      <FollowButton on={follow.isFollowed(team.id)} label={team.name} onToggle={() => follow.toggle(team.id)} />
    </li>
  )
}

export function PlayerRow({ player, follow, onNavigate }) {
  const { sportIcon } = useCatalog()
  const { team } = player
  return (
    <li className="result-row">
      <button className="rr-main" onClick={() => onNavigate({ type: 'player', playerId: player.id })}>
        <span className="player-num" style={{ '--team': team.color }} aria-hidden="true">{player.number}</span>
        <span className="rr-text">
          <span className="rr-title">{player.name}</span>
          <span className="rr-sub">
            #{player.number} {player.position} · {sportIcon(team.sport)} {team.name}
          </span>
        </span>
      </button>
      <FollowButton on={follow.isFollowed(team.id)} label={team.name} onToggle={() => follow.toggle(team.id)}>
        Follow team
      </FollowButton>
    </li>
  )
}
