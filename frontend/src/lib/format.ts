/** Presentation helpers: formatting, badges, and token inspection. */

import type { AnonymizationRule, FieldClassification } from './types'

export function formatTimestamp(value: string | null | undefined): string {
  if (!value) return 'never'
  const parsed = new Date(value.endsWith('Z') ? value : `${value}Z`)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatBoolean(value: boolean): string {
  return value ? 'yes' : 'no'
}

/** Render one decrypted cell value. */
export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'boolean') return formatBoolean(value)
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(2)
  return String(value)
}

export function percent(part: number, total: number): number {
  if (total <= 0) return 0
  return Math.round((part / total) * 100)
}

interface ClassificationMeta {
  label: string
  /** Complete, static badge class string (never assembled at runtime). */
  badge: string
  description: string
}

/** Field classification: colour plus an explicit label, never colour alone. */
export const CLASSIFICATION_META: Record<FieldClassification, ClassificationMeta> = {
  direct_identifier: {
    label: 'Direct identifier',
    badge: 'badge badge-sm badge-error',
    description: 'Identifies a person on its own; replaced by a hash or suppressed.',
  },
  quasi_identifier: {
    label: 'Quasi-identifier',
    badge: 'badge badge-sm badge-warning',
    description: 'Can identify a person in combination with other fields.',
  },
  sensitive: {
    label: 'Sensitive',
    badge: 'badge badge-sm badge-secondary',
    description: 'Reveals health or financial detail about a person.',
  },
  non_sensitive: {
    label: 'Non-sensitive',
    badge: 'badge badge-sm badge-neutral',
    description: 'Context or operational data with no personal detail.',
  },
}

export const RULE_LABEL: Record<AnonymizationRule, string> = {
  none: 'no transform',
  suppress: 'suppress',
  mask: 'mask',
  hash: 'hash',
  generalize: 'generalize',
  perturb: 'perturb',
}

/** Attribute categories map to the semantic badge colours. Each entry is a
 *  complete class string so no daisyUI class is ever assembled at runtime. */
const CATEGORY_BADGE: Record<string, string> = {
  role: 'badge badge-primary font-mono',
  dept: 'badge badge-secondary font-mono',
  clearance: 'badge badge-warning font-mono',
  site: 'badge badge-info font-mono',
  purpose: 'badge badge-accent font-mono',
  region: 'badge badge-neutral font-mono',
}

const CATEGORY_BADGE_SMALL: Record<string, string> = {
  role: 'badge badge-primary badge-sm font-mono',
  dept: 'badge badge-secondary badge-sm font-mono',
  clearance: 'badge badge-warning badge-sm font-mono',
  site: 'badge badge-info badge-sm font-mono',
  purpose: 'badge badge-accent badge-sm font-mono',
  region: 'badge badge-neutral badge-sm font-mono',
}

/** Look up the complete badge class string for an attribute's category. */
export function attributeBadgeClass(attribute: string, small = false): string {
  const category = attribute.split(':')[0]
  if (small) return CATEGORY_BADGE_SMALL[category] ?? 'badge badge-neutral badge-sm font-mono'
  return CATEGORY_BADGE[category] ?? 'badge badge-neutral font-mono'
}

export function categoryOf(attribute: string): string {
  return attribute.split(':')[0] ?? 'other'
}

/**
 * Decode the payload of a JWT for display. The signature is *not* verified here -
 * the server is the only thing that decides access - this is purely so the
 * dashboard can show which attribute set the session was minted with.
 */
export function decodeJwtPayload(token: string): Record<string, unknown> | null {
  const segment = token.split('.')[1]
  if (!segment) return null
  try {
    const padded = segment.replace(/-/g, '+').replace(/_/g, '/')
    const json = decodeURIComponent(
      atob(padded)
        .split('')
        .map((char) => `%${`00${char.charCodeAt(0).toString(16)}`.slice(-2)}`)
        .join(''),
    )
    const parsed: unknown = JSON.parse(json)
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : null
  } catch {
    return null
  }
}

export function shortHash(hash: string, length = 12): string {
  return hash.length > length ? `${hash.slice(0, length)}…` : hash
}
