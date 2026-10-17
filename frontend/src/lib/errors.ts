/** Normalise anything thrown by the generated client into a message + hint for the UI. */
export interface ApiProblem {
  message: string
  source?: string | null
  hint: string
  status?: number
  /** Where the user can fix it, when there's a page for that */
  action?: { label: string; to: '/connect'; search: { tab: 'espn' } }
}

export function describeError(err: unknown): ApiProblem {
  if (err instanceof TypeError) {
    return {
      message: 'Could not reach the FantasyEdge API.',
      hint: 'Start the backend with `python tasks.py api` (port 8000), then retry.',
    }
  }
  const body = (err ?? {}) as { detail?: unknown; source?: string | null; kind?: string }
  let message = 'Something went wrong.'
  if (typeof body.detail === 'string') message = body.detail
  else if (Array.isArray(body.detail) && body.detail.length) {
    const first = body.detail[0] as { msg?: string; loc?: unknown[] }
    message = `${first.loc?.slice(-1)[0] ?? 'input'}: ${first.msg ?? 'invalid'}`
  }
  const source = body.source ?? null
  let hint = 'Retry in a moment.'
  if (body.kind === 'espn_auth' || body.kind === 'espn_private') {
    return {
      message,
      source,
      hint: 'Copy fresh espn_s2 and SWID cookies from fantasy.espn.com (see "How do I find these?" on the ESPN tab).',
      action: { label: 'Paste fresh cookies', to: '/connect', search: { tab: 'espn' } },
    }
  }
  if (source === 'espn') hint = 'ESPN is not responding. Your last synced data is still available.'
  else if (source === 'local') hint = 'Run `python tasks.py data` to load NFL data, then retry.'
  else if (source === 'sleeper') hint = 'Sleeper is not responding. Your last synced data is still available.'
  else if (source === 'market') hint = 'Market values are unavailable; advice falls back to model values.'
  else if (/not found/i.test(message)) hint = 'Check the spelling, or reconnect your team.'
  return { message, source, hint }
}
