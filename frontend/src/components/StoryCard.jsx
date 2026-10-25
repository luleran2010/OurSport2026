import { timeAgo } from '../utils/time'

export default function StoryCard({ story, now, onNavigate }) {
  return (
    <button className="story-card" onClick={() => onNavigate({ type: 'story', storyId: story.id })}>
      <span className="story-meta"><span className="story-tag">{story.tag}</span>{timeAgo(story.publishedAt, now)}</span>
      <strong className="story-title">{story.title}</strong>
      <span className="story-summary">{story.summary}</span>
    </button>
  )
}
