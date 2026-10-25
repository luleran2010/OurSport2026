import { useState } from 'react'
import { timeAgo } from '../../../utils/time'
import { api } from '../../../api/client'

const TYPE_LABEL = {
  highlight: 'Highlight',
  update: 'Update',
  result: 'Final',
  score: 'Score',
}

export default function FeedPost({ post, now }) {
  const [liked, setLiked] = useState(false)
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState(null)
  const comments = post.comments ?? []

  // The new comment arrives back through the live feed stream.
  const submit = async (e) => {
    e.preventDefault()
    const text = draft.trim()
    if (!text || sending) return
    setSending(true)
    setError(null)
    try {
      await api.addComment(post.id, text)
      setDraft('')
    } catch (err) {
      setError(err.message)
    } finally {
      setSending(false)
    }
  }

  return (
    <article className={`post post--${post.type}`}>
      <header className="post-head">
        <span className="avatar" aria-hidden="true">{post.author.slice(0, 1)}</span>
        <div className="post-meta">
          <span className="post-author">{post.author}</span>
          <span className="post-time">{timeAgo(post.createdAt, now)}</span>
        </div>
        <span className="post-type">{TYPE_LABEL[post.type]}</span>
      </header>

      <p className="post-text">{post.text}</p>

      {post.media && (
        <div className="post-media" role="img" aria-label="Video highlight">
          <span className="play" aria-hidden="true">▶</span>
          <span className="duration">{post.media.duration}</span>
        </div>
      )}

      {post.result && (
        <div className="post-result">
          <span>{post.result.home}</span>
          <strong>{post.result.score[0]} – {post.result.score[1]}</strong>
          <span>{post.result.away}</span>
        </div>
      )}

      <footer className="post-actions">
        <button className={liked ? 'is-liked' : ''} aria-pressed={liked} onClick={() => setLiked((v) => !v)}>
          ♥ {post.likes + (liked ? 1 : 0)}
        </button>
        <button aria-expanded={open} onClick={() => setOpen((v) => !v)}>
          💬 {comments.length}
        </button>
        <button>↗ Share</button>
      </footer>

      {open && (
        <div className="comments">
          {comments.map((c) => (
            <div className="comment" key={c.id}>
              <span className="comment-author">{c.author}</span>
              <span className="comment-time">{timeAgo(c.createdAt, now)}</span>
              <p>{c.text}</p>
            </div>
          ))}
          <form className="comment-form" onSubmit={submit}>
            <label className="visually-hidden" htmlFor={`cf-${post.id}`}>Write a comment</label>
            <input
              id={`cf-${post.id}`}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Write a comment…"
            />
            <button className="btn btn--accent btn--sm" disabled={!draft.trim() || sending}>
              {sending ? '…' : 'Post'}
            </button>
          </form>
          {error && <p className="form-error" role="alert">Couldn’t post comment: {error}</p>}
        </div>
      )}
    </article>
  )
}
