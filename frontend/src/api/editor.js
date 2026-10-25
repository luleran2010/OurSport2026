// Editor desk (E1–E3) on the v1 editorial API: the review queue of stories the claim checker
// held (`blocked_claim`) or that need a human (`sensitive`), one review item with its fact
// sheet and check result, published / unpublished stories and readers' correction reports.
// The backend serves plain lists; filters, counts and pages are worked out here.
import { v1 } from './http'
import * as A from './adapt'

const id = encodeURIComponent
const REASON = { blocked_claim: 'blocked_claim', sensitive: 'sensitive_topic' }
const REASON_TEXT = {
  blocked_claim: 'The claim checker found a sentence the facts don’t back.',
  sensitive: 'Junior match with a red card: a person decides.',
}
const KIND_LABEL = { mistake: 'Mistake', privacy: 'Privacy', illegal: 'Illegal content', other: 'Other' }
const DAY_MS = 86_400_000

/** `deps`: `loadCatalog()` (tournament names) and `me()` (the signed-in editor). */
export function editorDesk({ loadCatalog, me }) {
  const matches = new Map()

  /** The match a story is about, as the screens show matches (cached; null when it isn't one). */
  function matchOf(s) {
    if (s.subject_type !== 'match') return Promise.resolve(null)
    if (!matches.has(s.subject_id)) {
      matches.set(s.subject_id, v1(`/matches/${id(s.subject_id)}`).then((p) => A.match(p.match)).catch(() => null))
    }
    return matches.get(s.subject_id)
  }

  const eventName = (s) => A.ref.tournaments[s.tournament_id]?.name ?? ''
  const tag = (s) => A.TAG[s.kind] ?? s.kind

  async function queueEntries() {
    await loadCatalog()
    return v1('/review-queue')
  }

  async function row(e) {
    const s = e.story
    const mine = e.claimed_by && e.claimed_by === me().id
    return {
      id: s.id, headline: s.headline, language: s.language, source: tag(s),
      reason: REASON[s.review_reason] ?? 'blocked_claim', reasonText: REASON_TEXT[s.review_reason] ?? '',
      priority: s.review_reason === 'sensitive' ? 'high' : 'normal',
      createdAt: Date.parse(s.updated_at), match: await matchOf(s), eventName: eventName(s),
      eventId: s.tournament_id, sport: A.ref.tournaments[s.tournament_id]?.sport ?? '',
      assignedToMe: Boolean(mine), assignedTo: e.claimed_by && !mine ? 'Another editor' : null,
    }
  }

  const options = (rows, key, label) => {
    const counts = new Map()
    for (const r of rows) if (r[key]) counts.set(r[key], (counts.get(r[key]) ?? 0) + 1)
    return [...counts].map(([value, count]) => ({ id: value, label: label(value, rows), count }))
  }

  /** The queue sorted high priority first, then longest waiting; the next item for "j" and after a decision. */
  async function sortedQueue() {
    const rows = await Promise.all((await queueEntries()).map(row))
    return rows.sort((a, b) => (a.priority === b.priority ? a.createdAt - b.createdAt : a.priority === 'high' ? -1 : 1))
  }

  async function nextAfter(storyId) {
    const rows = (await sortedQueue()).filter((r) => r.id !== storyId && (!r.assignedTo || r.assignedToMe))
    return rows[0]?.id ?? null
  }

  async function editorQueue(params = {}) {
    const all = await sortedQueue()
    const now = Date.now()
    const age = (r) => (now - r.createdAt) / 60_000
    const rows = all.filter((r) => (!params.reason || r.reason === params.reason)
      && (!params.sport || r.sport === params.sport) && (!params.event || r.eventId === params.event)
      && (!params.language || r.language === params.language)
      && (!params.assigned || (params.assigned === 'me' ? r.assignedToMe : !r.assignedTo && !r.assignedToMe))
      && (!params.age || (params.age === 'under_30' ? age(r) < 30 : params.age === 'over_30' ? age(r) >= 30 : age(r) >= 120)))
    const offset = Number(params.cursor ?? 0)
    const limit = params.limit ?? 25
    return {
      items: rows.slice(offset, offset + limit), total: rows.length,
      nextCursor: offset + limit < rows.length ? String(offset + limit) : null, updatedAt: now,
      counts: {
        all: all.length, unassigned: all.filter((r) => !r.assignedTo && !r.assignedToMe).length,
        mine: all.filter((r) => r.assignedToMe).length, high: all.filter((r) => r.priority === 'high').length,
        over_30: all.filter((r) => age(r) >= 30).length, over_120: all.filter((r) => age(r) >= 120).length,
      },
      filters: {
        reasons: options(all, 'reason', (v) => ({ blocked_claim: 'Blocked claim', sensitive_topic: 'Sensitive topic' })[v] ?? v),
        sports: options(all, 'sport', (v) => v.charAt(0).toUpperCase() + v.slice(1)),
        events: options(all, 'eventId', (v, rs) => rs.find((r) => r.eventId === v)?.eventName || 'Event'),
        languages: options(all, 'language', (v) => v.toUpperCase()),
      },
    }
  }

  /** E2: the story with the checker's flags on its sentences, the fact sheet and the history. */
  async function reviewItem(storyId) {
    await loadCatalog()
    const [{ story: s, claimed_by: claimedBy }, queue] = await Promise.all([
      v1(`/review-queue/${id(storyId)}`), sortedQueue(),
    ])
    const issues = (s.check_result?.issues ?? []).filter((i) => i.language === s.language)
    const flagsOf = (text) => [...new Map(issues.filter((i) => i.sentence === text) // one flag per distinct problem
      .map((i) => [`${i.kind}:${i.detail}`, { code: i.kind, reason: i.detail, quote: i.sentence }])).values()]
    const sentence = (text, factIds, n) => ({ id: n, text, factIds, flags: flagsOf(text) })
    const sentences = s.sentences.length ? s.sentences : [{ text: s.body, facts: [] }]
    const checked = s.check_result && 'passed' in s.check_result
    const mine = claimedBy && claimedBy === me().id
    const at = queue.findIndex((r) => r.id === s.id)
    const decided = { blocked: 'rejected', unpublished: 'unpublished' }[s.status]
    return {
      id: s.id, storyId: s.id, kind: 'story', language: s.language, version: s.version,
      status: decided ? 'decided' : 'open', updatedAt: Date.parse(s.updated_at),
      decision: decided ? { action: decided, by: 'an editor', at: Date.parse(s.updated_at), note: s.removal_reason } : null,
      tag: tag(s), author: 'AI writer', eventName: eventName(s), match: await matchOf(s),
      assignedToMe: Boolean(mine), assignedTo: claimedBy && !mine ? 'Another editor' : null,
      item: s.status === 'in_review'
        ? { priority: s.review_reason === 'sensitive' ? 'high' : 'normal', reason: REASON[s.review_reason] ?? 'blocked_claim', headline: s.headline }
        : null,
      check: checked
        ? { status: s.check_result.passed ? 'passed' : 'flagged', flags: issues.length, at: Date.parse(s.updated_at) }
        : { status: 'stale' },
      text: { title: s.headline, summary: '', body: [s.body] },
      annotated: {
        title: sentence(s.headline, [], 'h'), summary: [],
        body: [sentences.map((x, n) => sentence(x.text, x.facts ?? [], n))],
      },
      facts: s.facts.map((f) => ({ id: f.id, claim: f.claim, value: '', source: 'Match data', junior: false })),
      ruleVersion: null, correction: null,
      history: [
        ...s.versions.map((v) => ({
          action: v.edited_by ? 'edited' : 'regenerated', at: Date.parse(v.created_at),
          by: v.edited_by ? 'An editor' : 'AI writer', note: `Version ${v.version}: “${v.headline}”`,
        })),
        { action: s.status === 'in_review' ? 'submitted' : s.status, at: Date.parse(s.updated_at),
          by: s.status === 'in_review' ? 'Claim checker' : 'An editor', note: REASON_TEXT[s.review_reason] ?? null },
      ],
      nav: {
        position: at >= 0 ? at + 1 : null, total: queue.length,
        prevId: at > 0 ? queue[at - 1].id : null,
        nextId: at >= 0 ? queue[at + 1]?.id ?? null : queue[0]?.id ?? null,
      },
    }
  }

  /** "Take next" (`itemId` "next") or claim one item; the desk opens the result. */
  async function claimReview(itemId) {
    const item = itemId === 'next'
      ? await v1('/review-queue/take-next', { method: 'POST' })
      : await v1(`/review-queue/${id(itemId)}/claim`, { method: 'POST' })
    if (!item) throw Object.assign(new Error('Nothing left to take: the queue is empty.'), { code: 'empty' })
    return { id: item.story.id }
  }

  const check = async (storyId) => {
    const c = await v1(`/stories/${id(storyId)}/check`, { method: 'POST' })
    return { check: { status: c.passed ? 'passed' : 'flagged', flags: c.issues.length } }
  }

  const decide = (action) => async (storyId) => {
    await v1(`/stories/${id(storyId)}/${action}`, { method: 'POST' })
    return { nextId: await nextAfter(storyId) }
  }

  /** E3: published or unpublished stories with their open reports, filtered and paged here. */
  async function editorStories(params = {}) {
    await loadCatalog()
    const [published, unpublished, open] = await Promise.all([
      v1('/editor/stories?status=published'), v1('/editor/stories?status=unpublished'), v1('/corrections?status=open'),
    ])
    const reports = new Map()
    for (const c of open) reports.set(c.story_id, (reports.get(c.story_id) ?? 0) + 1)
    const now = Date.now()
    const item = (s) => ({
      id: s.id, title: s.headline, language: s.language, tag: tag(s), clubName: '', match: null,
      eventName: eventName(s), eventId: s.tournament_id, body: s.body,
      authorType: s.author_type === 'ai' ? 'ai' : 'manual', author: s.reviewed_by_editor ? 'AI, reviewed by an editor' : s.author_type === 'ai' ? 'AI writer' : '',
      publishedAt: Date.parse(s.published_at ?? s.updated_at), status: s.status,
      unpublishedAt: Date.parse(s.updated_at), unpublishedBy: 'an editor', unpublishReason: s.removal_reason ?? '',
      correctedAt: s.corrected_at ? Date.parse(s.corrected_at) : null, correctionNote: null,
      openCorrections: reports.get(s.id) ?? 0, correctItemId: s.id,
    })
    const list = (params.status === 'unpublished' ? unpublished : published).map(item)
    const since = { '24h': DAY_MS, '7d': 7 * DAY_MS, '30d': 30 * DAY_MS }[params.date]
    const q = (params.q ?? '').toLowerCase()
    const rows = list.filter((s) => (!q || s.title.toLowerCase().includes(q) || s.body.toLowerCase().includes(q))
      && (!since || now - s.publishedAt <= since) && (!params.event || s.eventId === params.event)
      && (!params.author || s.authorType === params.author)
      && (!params.corrected || (params.corrected === 'yes' ? s.correctedAt : params.corrected === 'no' ? !s.correctedAt : s.openCorrections > 0)))
    const offset = Number(params.cursor ?? 0)
    const limit = params.limit ?? 30
    return {
      items: rows.slice(offset, offset + limit), total: rows.length, updatedAt: now,
      nextCursor: offset + limit < rows.length ? String(offset + limit) : null,
      counts: {
        published: published.length, unpublished: unpublished.length,
        corrected: published.filter((s) => s.corrected_at).length, reported: reports.size,
      },
      events: options(list, 'eventId', (v, rs) => rs.find((r) => r.eventId === v)?.eventName || 'Event')
        .map((o) => ({ id: o.id, label: o.label, count: o.count })),
    }
  }

  async function editorCorrections(status = 'open') {
    const [open, fixed, rejected] = await Promise.all(['open', 'fixed', 'rejected'].map((st) => v1(`/corrections?status=${st}`)))
    const byStatus = { open, fixed, rejected, all: [...open, ...fixed, ...rejected] }
    return {
      updatedAt: Date.now(), counts: { open: open.length, fixed: fixed.length, rejected: rejected.length },
      items: byStatus[status].map((c) => ({
        id: c.id, message: c.text, correctValue: null, storyId: c.story_id, itemId: c.story_id,
        storyTitle: c.story_headline, storyStatus: c.story_status, match: null,
        fieldLabel: KIND_LABEL[c.kind] ?? c.kind, source: 'fan', reporter: 'A reader',
        createdAt: Date.parse(c.created_at), status: c.status, assignedTo: null, resolution: c.note,
      })),
    }
  }

  return {
    editorQueue, reviewItem, claimReview, editorStories, editorCorrections,
    editStory: (storyId, body) => v1(`/stories/${id(storyId)}`, {
      method: 'PATCH', headers: { 'If-Match': `"${body.version}"` },
      body: { headline: body.title, body: [body.summary, ...body.body].filter(Boolean).join(' ') },
    }),
    checkStory: check,
    approveStory: decide('approve'),
    rejectStory: decide('reject'),
    regenerateStory: async (storyId) => {
      await v1(`/stories/${id(storyId)}/regenerate`, { method: 'POST' })
      // the rewrite is checked at once: published when it passes, otherwise back in the queue
      const held = (await sortedQueue()).some((r) => r.id === storyId)
      return { nextId: held ? storyId : await nextAfter(storyId), held }
    },
    unpublishStory: (storyId, reason) => v1(`/stories/${id(storyId)}/unpublish`, { method: 'POST', body: { reason } }),
    resolveCorrection: (cid, status, note) => v1(`/corrections/${id(cid)}`, { method: 'PATCH', body: { status, note } }),
  }
}
