import { describe, expect, it } from 'vitest'

import { describeError } from './errors'

describe('describeError', () => {
  it('sends an expired ESPN login to the cookie form', () => {
    const p = describeError({ detail: 'Your ESPN login has expired — paste fresh cookies.', kind: 'espn_auth', source: 'espn' })
    expect(p.message).toMatch(/expired/)
    expect(p.hint).toMatch(/espn_s2 and SWID/)
    expect(p.action).toEqual({ label: 'Paste fresh cookies', to: '/connect', search: { tab: 'espn' } })
  })

  it('treats a private league without cookies the same way', () => {
    expect(describeError({ detail: 'private', kind: 'espn_private' }).action?.search.tab).toBe('espn')
  })

  it('explains an ESPN outage without asking for cookies', () => {
    const p = describeError({ detail: 'espn is unavailable right now.', source: 'espn' })
    expect(p.hint).toMatch(/ESPN is not responding/)
    expect(p.action).toBeUndefined()
  })
})
