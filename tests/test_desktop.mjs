// Self-check for desktop/plugin.js, the banner above the desktop app's composer. It runs in jsdom with
// the React stack Hermes' desktop ships; no app, no network. Install that stack next to this file once:
//   npm install --prefix tests --no-save --no-package-lock react@19.2.7 react-dom@19.2.7 @tanstack/react-query@5.101.2 jsdom@29.1.1
//   node tests/test_desktop.mjs
import { readFile } from 'node:fs/promises'
import assert from 'node:assert/strict'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><div id="root"></div>')
Object.assign(globalThis, { window: dom.window, document: dom.window.document, IS_REACT_ACT_ENVIRONMENT: true })
const React = await import('react')
const jsxRuntime = await import('react/jsx-runtime')
const { createRoot } = await import('react-dom/client')
const { QueryClient, QueryClientProvider, useQuery } = await import('@tanstack/react-query')

// The desktop's side of it: a readable atom per piece of state, and the RPC that runs `/optimized json <id>`.
function atom(value) {
  const listeners = new Set()
  return {
    get: () => value,
    set(next) {
      value = next
      listeners.forEach(listener => listener())
    },
    subscribe(listener) {
      listeners.add(listener)
      return () => listeners.delete(listener)
    }
  }
}
const latest = {} // what the Python half has recorded: session id -> its newest entry
const requests = []
const host = {
  state: { busy: atom(false), focusedStoredSessionId: atom(null) },
  async request(method, params) {
    requests.push(params.arg)
    assert.equal(method, 'command.dispatch')
    return { output: JSON.stringify(latest[params.arg.split(' ')[1]] ?? null) }
  }
}
const sdk = {
  Codicon: () => null,
  COMPOSER_AREAS: { top: 'composer:top' },
  CopyButton: () => null,
  host,
  useQuery,
  useValue: store => React.useSyncExternalStore(store.subscribe, store.get)
}

// Load plugin.js the way the desktop does: its imports point at the app's own modules.
const source = await readFile(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
async function load(modules, tag) {
  globalThis[tag] = modules
  const shim = name => {
    const names = Object.keys(modules[name]).filter(key => key !== 'default' && /^[A-Za-z_$][\w$]*$/.test(key))
    const code = `const m = globalThis.${tag}[${JSON.stringify(name)}]; export default m.default ?? m; ` +
      `export const { ${names.join(', ')} } = m;`
    return `data:text/javascript,${encodeURIComponent(code)}`
  }
  const code = source.replace(/from '(@hermes\/plugin-sdk|react\/jsx-runtime|react)'/g, (_, name) => `from '${shim(name)}'`)
  return (await import(`data:text/javascript,${encodeURIComponent(`${code}\n// ${tag}`)}`)).default
}
const plugin = await load({ '@hermes/plugin-sdk': sdk, react: React, 'react/jsx-runtime': jsxRuntime }, '__desktop')

const areas = []
plugin.register({ register: area => areas.push(area) })
assert.deepEqual(areas.map(area => area.area), ['composer:top'])

// The desktop's own query defaults (apps/desktop/src/lib/query-client.ts): results count as fresh for 60 s.
const client = new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false, staleTime: 60_000 } } })
const root = createRoot(document.getElementById('root'))
const settle = ms => React.act(() => new Promise(resolve => setTimeout(resolve, ms)))
const shows = async (change = () => {}) => {
  await React.act(async () => change())
  await settle(50)
  return document.getElementById('root').textContent
}
const entry = (id, status, extra = {}) => ({ id, status, model: 'fake-small', seconds: 1.2, optimized: `Prompt ${id}.`, ...extra })
await React.act(async () =>
  root.render(React.createElement(QueryClientProvider, { client }, React.createElement(areas[0].render)))
)

// An open chat shows its last result.
latest.s1 = entry('A', 'applied')
assert.match(await shows(() => host.state.focusedStoredSessionId.set('s1')), /Optimized · fake-small · 1.2s\s*Prompt A\./)

// Next message: the previous result is not passed off as this one's while the optimizer works on it…
const before = requests.length
assert.equal(await shows(() => host.state.busy.set(true)), '')
latest.s1 = entry('B', 'running')
await settle(3100) // the banner polls every 3 s while a turn runs
assert.match(document.getElementById('root').textContent, /Optimizing prompt…/)
// …and the moment the turn ends, the new result is there (not the cached one from before the turn).
latest.s1 = entry('B', 'applied')
assert.match(await shows(() => host.state.busy.set(false)), /Prompt B\./)
assert.equal(requests.length - before, 3) // turn start, one poll, turn end: nothing more

// A quick turn, over before a poll: the result still shows as soon as it ends.
await shows(() => host.state.busy.set(true))
latest.s1 = entry('C', 'applied')
assert.match(await shows(() => host.state.busy.set(false)), /Prompt C\./)

// A message the optimizer skips (too short, a slash command …) was sent as typed: no banner, and not the last one.
await shows(() => host.state.busy.set(true))
latest.s1 = entry('D', 'skipped', { reason: 'too short' })
assert.equal(await shows(() => host.state.busy.set(false)), '')

// A new chat: its id appears when Hermes creates the session, before the turn starts and before anything is
// recorded. The first result still shows when the turn ends.
await shows(() => host.state.focusedStoredSessionId.set(null))
await shows(() => host.state.focusedStoredSessionId.set('s2'))
await shows(() => host.state.busy.set(true))
latest.s2 = entry('E', 'applied')
assert.match(await shows(() => host.state.busy.set(false)), /Prompt E\./)

// A failure: the message went as typed, and the reason is one hover away.
await shows(() => host.state.busy.set(true))
latest.s2 = entry('F', 'error', { error: 'endpoint down' })
assert.match(await shows(() => host.state.busy.set(false)), /Optimizer skipped — sent as typed/)
assert.equal(document.querySelector('[title="endpoint down"]')?.textContent.includes('sent as typed'), true)

await React.act(async () => root.unmount())
client.clear()

// Desktop builds before Hermes v0.20.2 have no turn state to follow: no banner rather than a broken composer.
const old = { ...host, state: { activeSessionId: atom(null) } }
const legacy = await load({ '@hermes/plugin-sdk': { ...sdk, host: old }, react: React, 'react/jsx-runtime': jsxRuntime },
  '__legacy')
const none = []
legacy.register({ register: area => none.push(area) })
assert.deepEqual(none, [])

console.log('ok: all desktop banner self-checks passed')
