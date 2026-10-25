import { useState } from 'react'
import { useLocation, useSearchParams } from 'react-router'
import ClubCrest from '../../components/ClubCrest'
import TeamBadge from '../../components/TeamBadge'
import ShareButton from '../../components/ShareButton'
import { useMeContext } from '../../app/providers/me'
import { useLoad } from '../../api/useLoad'
import { api } from '../../api/client'
import RichText from '../../components/RichText'
import { clockTime, formatDate as formatDay } from '../../utils/time'

const LANG_NAMES = { en: 'English', fi: 'Suomi', bn: 'বাংলা' }
const LOCALE = { en: 'en-GB', fi: 'fi-FI', bn: 'bn-BD' }

// Story-page wording in each story language (the rest of the app is English for now).
const UI = {
  en: {
    ai: 'AI-generated from club-entered data',
    writtenBy: (n) => `Written by ${n}`,
    corrected: (d) => `Corrected on ${d}`,
    language: 'Language',
    why: 'Why?',
    whyHint: 'The match report uses these facts. Any separately labeled fictional team flavor is not a match fact. Unsupported names and numbers are blocked from the factual report.',
    related: 'Related',
    supportedBy: 'Match report supported by',
    share: '↗ Share',
    copied: '✓ Link copied',
    report: 'Report an error',
    reportPlaceholder: 'What’s wrong in this story?',
    send: 'Send',
    cancel: 'Cancel',
    thanks: 'Thanks — the editors will check it.',
    live: 'LIVE',
    fullTime: 'Full time',
    facts: {
      final_score: 'Final score', competition: 'Competition', venue: 'Venue', ended_at: 'Full time',
      kickoff_at: 'Kick-off', goal: 'Goal', table_move: 'Table position',
      head_to_head: 'Head-to-head (wins · draws · wins, games)',
    },
  },
  fi: {
    ai: 'Tekoälyn tuottama seuran syöttämistä tiedoista',
    writtenBy: (n) => `Kirjoittanut ${n}`,
    corrected: (d) => `Korjattu ${d}`,
    language: 'Kieli',
    why: 'Miksi?',
    whyHint: 'Otteluraportti perustuu näihin tietoihin. Erikseen merkitty kuvitteellinen joukkuekuvaus ei ole ottelufakta. Muita nimiä ja lukuja ei julkaista faktaraportissa.',
    related: 'Liittyvät',
    supportedBy: 'Otteluraportin tukijat',
    share: '↗ Jaa',
    copied: '✓ Linkki kopioitu',
    report: 'Ilmoita virheestä',
    reportPlaceholder: 'Mikä jutussa on väärin?',
    send: 'Lähetä',
    cancel: 'Peruuta',
    thanks: 'Kiitos – toimitus tarkistaa asian.',
    live: 'LIVE',
    fullTime: 'Päättynyt',
    facts: {
      final_score: 'Lopputulos', competition: 'Sarja', venue: 'Paikka', ended_at: 'Päättyi',
      kickoff_at: 'Alkaa', goal: 'Maali', table_move: 'Sarjasijoitus',
      head_to_head: 'Keskinäiset (voitot · tasapelit · voitot, ottelut)',
    },
  },
  bn: {
    ai: 'ক্লাবের দেওয়া তথ্য থেকে এআই-এর তৈরি',
    writtenBy: (n) => `লিখেছেন ${n}`,
    corrected: (d) => `সংশোধিত ${d}`,
    language: 'ভাষা',
    why: 'কেন?',
    whyHint: 'ম্যাচ রিপোর্টটি এই তথ্যগুলোর ভিত্তিতে লেখা। আলাদা করে চিহ্নিত কাল্পনিক দলের পরিচিতি ম্যাচের তথ্য নয়। তথ্যসমর্থিত অংশে অসমর্থিত নাম ও সংখ্যা প্রকাশ করা হয় না।',
    related: 'সম্পর্কিত',
    supportedBy: 'ম্যাচ রিপোর্টের পৃষ্ঠপোষক',
    share: '↗ শেয়ার করুন',
    copied: '✓ লিংক কপি হয়েছে',
    report: 'ভুল জানান',
    reportPlaceholder: 'লেখায় কী ভুল আছে?',
    send: 'পাঠান',
    cancel: 'বাতিল',
    thanks: 'ধন্যবাদ — সম্পাদকেরা বিষয়টি দেখবেন।',
    live: 'লাইভ',
    fullTime: 'খেলা শেষ',
    facts: {
      final_score: 'চূড়ান্ত ফলাফল', competition: 'প্রতিযোগিতা', venue: 'ভেন্যু', ended_at: 'খেলা শেষ',
      kickoff_at: 'খেলা শুরু', goal: 'গোল', table_move: 'টেবিলে অবস্থান',
      head_to_head: 'মুখোমুখি (জয় · ড্র · জয়, ম্যাচ)',
    },
  },
}

function preferredLanguage() {
  const langs = navigator.languages ?? [navigator.language ?? 'en']
  return langs.map((l) => l.slice(0, 2)).find((l) => l in UI) ?? 'en'
}

function formatDate(ts, lang, withTime = true) {
  const d = new Date(ts)
  const date = formatDay(d, { long: true, locale: LOCALE[lang] })
  return withTime ? `${date}, ${clockTime(d, LOCALE[lang])}` : date
}

function ReportError({ storyId, t }) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [status, setStatus] = useState('idle') // idle | sending | sent | error
  const [error, setError] = useState('')

  if (status === 'sent') return <p className="report-thanks" role="status">{t.thanks}</p>
  if (!open) return <button className="link-btn report-link" onClick={() => setOpen(true)}>⚑ {t.report}</button>

  const send = async (e) => {
    e.preventDefault()
    setStatus('sending')
    try {
      await api.reportStoryError(storyId, text.trim())
      setStatus('sent')
    } catch (err) {
      setError(err.message)
      setStatus('error')
    }
  }
  return (
    <form className="report-form" onSubmit={send}>
      <label className="visually-hidden" htmlFor="report-text">{t.report}</label>
      <textarea
        id="report-text"
        rows={3}
        minLength={5}
        maxLength={1000}
        required
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={t.reportPlaceholder}
        autoFocus
      />
      {status === 'error' && <p className="form-error" role="alert">{error}</p>}
      <div className="modal-actions">
        <button type="button" className="btn btn--ghost btn--sm" onClick={() => setOpen(false)}>{t.cancel}</button>
        <button className="btn btn--accent btn--sm" disabled={status === 'sending' || text.trim().length < 5}>{t.send}</button>
      </div>
    </form>
  )
}

export default function StoryView({ storyId, onNavigate }) {
  const { me } = useMeContext()
  const [params, setParams] = useSearchParams()
  const location = useLocation()
  // Members' chosen language (F10) first, then the browser's.
  const [fallbackLang] = useState(() => (me?.signedIn ? me.language : preferredLanguage()))
  const requested = params.get('lang') ?? fallbackLang
  const state = useLoad(() => api.story(storyId, requested), `${storyId}:${requested}`)

  if (state.status === 'error' && !state.data) return <p className="empty">Story not found.</p>
  if (!state.data) return <p className="page-sub">Loading…</p>

  const { story, related, sponsors = [] } = state.data
  const lang = story.language in UI ? story.language : 'en'
  const t = UI[lang]
  const setLang = (l) => setParams({ lang: l }, { replace: true, state: location.state })

  return (
    <article className="story" lang={lang}>
      {related.club && (
        <button className="story-club" onClick={() => onNavigate({ type: 'club', clubId: related.club.id, tab: 'news' })}>
          <ClubCrest club={related.club} size={24} /> {related.club.name}
        </button>
      )}
      {related.tournament && (
        <button className="story-club" onClick={() => onNavigate({ type: 'event', eventId: related.tournament.id, tab: 'news' })}>
          🏆 {related.tournament.name}
        </button>
      )}

      <span className="story-tag">{story.tag}</span>
      <h1>{story.title}</h1>

      <div className="story-byline">
        {story.authorType === 'ai' ? (
          <span className="ai-label"><span aria-hidden="true">✦</span> {story.aiLabel ?? t.ai}</span>
        ) : (
          <span className="editor-label">{t.writtenBy(story.author)}</span>
        )}
        <time dateTime={new Date(story.publishedAt).toISOString()}>{formatDate(story.publishedAt, lang)}</time>
      </div>

      {story.availableLanguages.length > 1 && (
        <div className="lang-switch" role="group" aria-label={t.language}>
          {story.availableLanguages.map((l) => (
            <button
              key={l}
              lang={l}
              className={l === story.language ? 'is-active' : ''}
              aria-pressed={l === story.language}
              onClick={() => setLang(l)}
            >
              {LANG_NAMES[l] ?? l}
            </button>
          ))}
        </div>
      )}

      {story.correctedAt && (
        <p className="story-corrected" role="note">
          <b>{(t.corrected ?? UI.en.corrected)(formatDate(story.correctedAt, lang, false))}</b>
          {story.correctionNote ? ` — ${story.correctionNote}` : ''}
        </p>
      )}

      {story.imageUrl && <img className="story-image" src={story.imageUrl} alt="" loading="lazy" />}
      {story.summary && <p className="story-lead">{story.summary}</p>}
      {story.body.map((para, i) => <RichText key={i} text={para} />)}

      {story.facts.length > 0 && (
        <details className="why">
          <summary>{t.why}</summary>
          <p className="why-hint">{t.whyHint}</p>
          <dl className="fact-list">
            {story.facts.map((f, i) => (
              <div key={i}>
                <dt>{t.facts[f.key] ?? f.key}</dt>
                <dd>{f.at ? formatDate(f.at, lang) : f.value}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}

      {(related.matches.length > 0 || related.teams.length > 0) && (
        <section className="story-related" aria-labelledby="rel-h">
          <h2 id="rel-h">{t.related}</h2>
          <div className="related-links">
            {related.matches.map((m) => (
              <button key={m.id} className="related-match" onClick={() => onNavigate({ type: 'match', matchId: m.id })}>
                <TeamBadge team={m.home} size={22} />
                <span>
                  {m.home.short}{' '}
                  {m.status === 'finished' ? `${m.score[0]}–${m.score[1]}` : m.status === 'live' ? t.live : clockTime(m.startsAt)}{' '}
                  {m.away.short}
                </span>
                <TeamBadge team={m.away} size={22} />
                <span className="related-sub">{m.status === 'finished' ? t.fullTime : m.status === 'upcoming' ? formatDate(m.startsAt, lang, false) : ''}</span>
              </button>
            ))}
            {related.teams.map((team) => (
              <button key={team.id} className="related-team" onClick={() => onNavigate({ type: 'team', teamId: team.id })}>
                <TeamBadge team={team} size={20} /> {team.name}
              </button>
            ))}
          </div>
        </section>
      )}

      {sponsors.length > 0 && (
        <footer className="sponsor-strip sponsor-strip--report" aria-label="Report sponsors">
          <span className="sponsor-label">{t.supportedBy}</span>
          <ul>
            {sponsors.map((sp) => {
              const mark = sp.logoUrl ? <img src={sp.logoUrl} alt={sp.name} /> : <span className="sponsor-wordmark">{sp.name}</span>
              return <li key={sp.id}>{sp.url ? <a href={sp.url} target="_blank" rel="sponsored noopener noreferrer">{mark}</a> : mark}</li>
            })}
          </ul>
        </footer>
      )}

      <div className="story-actions">
        <ShareButton title={story.title} text={story.title} label={t.share} copiedLabel={t.copied} />
        {me?.signedIn && <ReportError key={story.id} storyId={story.id} t={t} />}
      </div>
    </article>
  )
}
