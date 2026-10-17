import { useCallback, useState } from 'react'

export interface History<T> {
  past: T[]
  present: T
  future: T[]
}

export const history = {
  init<T>(present: T): History<T> {
    return { past: [], present, future: [] }
  },
  push<T>(h: History<T>, next: T): History<T> {
    return { past: [...h.past, h.present], present: next, future: [] }
  },
  undo<T>(h: History<T>): History<T> {
    if (h.past.length === 0) return h
    return { past: h.past.slice(0, -1), present: h.past[h.past.length - 1], future: [h.present, ...h.future] }
  },
  redo<T>(h: History<T>): History<T> {
    if (h.future.length === 0) return h
    return { past: [...h.past, h.present], present: h.future[0], future: h.future.slice(1) }
  },
}

/** In-memory undo/redo for one page session (not persisted). */
export function useHistory<T>(initial: T) {
  const [h, setH] = useState(() => history.init(initial))
  return {
    state: h.present,
    canUndo: h.past.length > 0,
    canRedo: h.future.length > 0,
    set: useCallback((next: T) => setH((cur) => history.push(cur, next)), []),
    undo: useCallback(() => setH((cur) => history.undo(cur)), []),
    redo: useCallback(() => setH((cur) => history.redo(cur)), []),
    /** Start over from `value` with an empty history (e.g. a different week was loaded). */
    reset: useCallback((value: T) => setH(history.init(value)), []),
  }
}
