/**
 * hermes-prompt-optimizer — desktop half.
 * Shows the optimized version of your last message in a small banner above the composer.
 * Display-only: nothing here reaches the transcript or the model. Data comes from the Python
 * half's `/optimized json <session>` command over the gateway's command.dispatch RPC, so no
 * extra backend is needed.
 */
import { Codicon, COMPOSER_AREAS, CopyButton, host, useQuery, useValue } from '@hermes/plugin-sdk'
import { useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'hermes-prompt-optimizer'

export async function fetchLatest(sessionId) {
  // ponytail: asks the active gateway only — a tile owned by another profile shows no banner
  // (switch to host.requestProfile(focusedSessionProfile, …) if you chat across profiles).
  try {
    const res = await host.request('command.dispatch', { name: 'optimized', arg: `json ${sessionId}` })
    return res && res.output ? JSON.parse(res.output) : null
  } catch {
    return null // Python half disabled / gateway unreachable → show nothing
  }
}

const MUTED = { color: 'var(--ui-text-tertiary)' }
const ICON_BUTTON = { background: 'none', border: 0, padding: 2, cursor: 'pointer', color: 'inherit', display: 'inline-flex' }

function summary(entry) {
  switch (entry.status) {
    case 'running':
      return 'Optimizing prompt…'
    case 'applied': {
      const bits = [entry.model, `${entry.seconds}s`]
      if ((entry.candidates || []).length > 1) bits.push(`best of ${entry.candidates.length} (#${entry.picked + 1})`)
      return `Optimized · ${bits.join(' · ')}`
    }
    case 'unchanged':
      return 'Prompt already clear — sent as typed'
    default: // error / late
      return 'Optimizer skipped — sent as typed'
  }
}

export function Banner() {
  const sessionId = useValue(host.state.focusedStoredSessionId)
  const busy = useValue(host.state.busy)
  const [open, setOpen] = useState(false)
  const [dismissed, setDismissed] = useState(null)
  const { data } = useQuery({
    queryKey: [ID, sessionId, busy],
    queryFn: () => fetchLatest(sessionId),
    enabled: Boolean(sessionId),
    // ponytail: polls only while a turn runs; a push event would need a core hook-to-UI channel
    refetchInterval: busy ? 3000 : false // the SDK guide: don't poll host.request faster than a few seconds
  })

  if (!data || data.id === dismissed || (data.status === 'running' && !busy)) {
    return null
  }

  const applied = data.status === 'applied'
  const firstLine = applied ? (data.optimized || '').split('\n').find(line => line.trim()) || '' : ''

  return jsxs('div', {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 4,
      margin: '0 0 6px',
      padding: '4px 8px',
      borderRadius: 8,
      border: '1px solid var(--ui-stroke-secondary)',
      fontSize: 12,
      minWidth: 0
    },
    children: [
      jsxs('div', {
        style: { display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 },
        title: data.error || undefined,
        children: [
          jsx(Codicon, { name: data.status === 'running' ? 'loading' : 'sparkle', spinning: data.status === 'running', size: 13 }),
          jsx('span', { style: { whiteSpace: 'nowrap', ...(applied ? {} : MUTED) }, children: summary(data) }),
          jsx('span', {
            style: { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', ...MUTED },
            children: applied && !open ? firstLine : ''
          }),
          applied &&
            jsx('button', {
              type: 'button',
              style: ICON_BUTTON,
              'aria-label': open ? 'Hide optimized prompt' : 'Show optimized prompt',
              title: open ? 'Hide optimized prompt' : 'Show optimized prompt',
              onClick: () => setOpen(!open),
              children: jsx(Codicon, { name: open ? 'chevron-down' : 'chevron-right', size: 13 })
            }),
          applied && jsx(CopyButton, { text: data.optimized, appearance: 'icon', label: 'Copy optimized prompt' }),
          jsx('button', {
            type: 'button',
            style: ICON_BUTTON,
            'aria-label': 'Dismiss',
            title: 'Dismiss',
            onClick: () => setDismissed(data.id),
            children: jsx(Codicon, { name: 'close', size: 13 })
          })
        ]
      }),
      applied &&
        open &&
        jsx('div', {
          style: { whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: '40vh', overflowY: 'auto', lineHeight: 1.45 },
          children: data.optimized
        })
    ]
  })
}

export default {
  id: ID,
  name: 'Prompt Optimizer',
  description: 'Shows the optimized version of your last message above the composer.',
  register(ctx) {
    ctx.register({ id: 'banner', area: COMPOSER_AREAS.top, render: () => jsx(Banner, {}) })
  }
}
