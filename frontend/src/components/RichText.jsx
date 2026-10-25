/**
 * Basic formatting for manual posts (P5): **bold**, *italic* and "- " list lines inside a paragraph.
 * Built as React elements (no HTML from the text is ever injected).
 */
function inline(text, keyBase) {
  const out = []
  const re = /\*\*(.+?)\*\*|\*(.+?)\*/g
  let last = 0
  let m
  let i = 0
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index))
    out.push(m[1] !== undefined ? <strong key={`${keyBase}-${i++}`}>{m[1]}</strong> : <em key={`${keyBase}-${i++}`}>{m[2]}</em>)
    last = re.lastIndex
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

export default function RichText({ text, className }) {
  const lines = text.split('\n')
  const blocks = []
  for (const line of lines) {
    const item = /^\s*[-•]\s+(.*)$/.exec(line)
    const prev = blocks[blocks.length - 1]
    if (item) {
      if (prev?.type === 'ul') prev.items.push(item[1])
      else blocks.push({ type: 'ul', items: [item[1]] })
    } else if (line.trim()) {
      if (prev?.type === 'p') prev.lines.push(line)
      else blocks.push({ type: 'p', lines: [line] })
    }
  }
  return blocks.map((b, i) =>
    b.type === 'ul' ? (
      <ul key={i} className={className}>{b.items.map((it, j) => <li key={j}>{inline(it, `${i}-${j}`)}</li>)}</ul>
    ) : (
      <p key={i} className={className}>{b.lines.map((l, j) => <span key={j}>{j > 0 && <br />}{inline(l, `${i}-${j}`)}</span>)}</p>
    ),
  )
}
