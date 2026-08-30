import { apiRequest } from '../services/api'
import { allows } from '../lib/consent'

/**
 * Play tickets and score submission, built to survive having no connection.
 *
 * The server issues tickets in batches and validates every submission, so the
 * client never chooses its own seed and never decides what a run was worth.
 * That constraint is what forces the queue below: a run finished offline has
 * to hold onto its result until there's somewhere to send it.
 *
 * localStorage rather than IndexedDB on purpose. The queue is a handful of
 * small records, IndexedDB's asynchronous API would have to be threaded
 * through the game loop for no benefit, and the failure mode that actually
 * matters here - storage throwing outright in a private window - has to be
 * handled either way.
 */

const TICKETS_KEY = 'fp-game-tickets'
const QUEUE_KEY = 'fp-game-queue'

export interface Ticket {
  token: string
  seed: number
  max_payout: number
}

export interface RunResult {
  token: string
  payout: number
  delivered: number
  lost: number
  duration_ms: number
}

export interface LeaderboardEntry {
  rank: number
  name: string
  payout: number
  delivered: number
  lost: number
  recorded_at: string | null
}

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    // Blocked storage or malformed JSON - either way, start clean rather
    // than taking the game down.
    return fallback
  }
}

function write(key: string, value: unknown) {
  // Without consent for the game category nothing is kept between visits.
  // A run still plays and still submits while online; what's lost is the
  // offline queue surviving a reload, which is the trade that was agreed.
  if (!allows('game')) return
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // Nothing to do: the run still counts for this session, it just won't
    // survive a reload.
  }
}

// ---- tickets ---------------------------------------------------------

export function heldTickets(): Ticket[] {
  return read<Ticket[]>(TICKETS_KEY, [])
}

/** Tops the local supply back up. Safe to call whenever online. */
export async function refillTickets(): Promise<Ticket[]> {
  const held = heldTickets()
  try {
    const response = await apiRequest<{ issued: Ticket[] }>('/api/game/sessions', { method: 'POST' })
    const merged = [...held, ...response.issued]
    write(TICKETS_KEY, merged)
    return merged
  } catch {
    // Offline, or signed out. Whatever is already banked still plays.
    return held
  }
}

/** Takes the next ticket, removing it from the local supply. */
export function claimTicket(): Ticket | null {
  const held = heldTickets()
  const next = held.shift()
  if (!next) return null
  write(TICKETS_KEY, held)
  return next
}

// ---- results ---------------------------------------------------------

export function queuedResults(): RunResult[] {
  return read<RunResult[]>(QUEUE_KEY, [])
}

/**
 * Submits a finished run, queueing it if that isn't possible right now.
 * Returns whether it reached the server.
 */
export async function submitRun(result: RunResult): Promise<boolean> {
  if (!navigator.onLine) {
    write(QUEUE_KEY, [...queuedResults(), result])
    return false
  }
  try {
    await apiRequest('/api/game/scores', { method: 'POST', body: JSON.stringify(result) })
    return true
  } catch (err) {
    // A 400 means the server judged the run invalid - an expired or already
    // used ticket. Re-queueing that would retry forever, so it's dropped.
    const rejected = err instanceof Error && /already|expired|Unknown|higher than|possible/i.test(err.message)
    if (!rejected) {
      write(QUEUE_KEY, [...queuedResults(), result])
    }
    return false
  }
}

/** Drains the queue. Called on reconnect and on load. */
export async function flushQueue(): Promise<number> {
  if (!navigator.onLine) return 0
  const pending = queuedResults()
  if (pending.length === 0) return 0

  const stillPending: RunResult[] = []
  let sent = 0
  for (const result of pending) {
    try {
      await apiRequest('/api/game/scores', { method: 'POST', body: JSON.stringify(result) })
      sent++
    } catch (err) {
      const rejected = err instanceof Error && /already|expired|Unknown|higher than|possible/i.test(err.message)
      // Only a transport failure is worth keeping; a rejection never
      // becomes valid later.
      if (!rejected) stillPending.push(result)
    }
  }
  write(QUEUE_KEY, stillPending)
  return sent
}

export function getLeaderboard(period: 'week' | 'month') {
  return apiRequest<{ period: string; entries: LeaderboardEntry[] }>(
    `/api/game/leaderboard?period=${period}`,
  )
}
