// Placeholders until the real documents are written (linked from sign-up consent).
const COPY = {
  terms: {
    title: 'Terms of use',
    points: [
      'OurSport AI shows results, scenarios and stories based on data entered by clubs and scorers.',
      'AI-written stories are labelled and generated only from the match fact sheet.',
      'Be respectful in comments. Clubs can remove content that breaks their rules.',
    ],
  },
  privacy: {
    title: 'Privacy policy',
    points: [
      'We store your email, name, language, what you follow and your alert settings to run the service.',
      'Junior players’ profiles are private and only visible to linked guardians.',
      'You can delete your account at any time from Account & plan.',
    ],
  },
}

export default function LegalView({ kind }) {
  const c = COPY[kind]
  return (
    <div className="auth-card legal">
      <h1>{c.title}</h1>
      <p className="page-sub">Draft — the full text will be published before launch. In short:</p>
      <ul>{c.points.map((p) => <li key={p}>{p}</li>)}</ul>
    </div>
  )
}
