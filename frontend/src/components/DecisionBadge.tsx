import { CircleCheck, CircleX } from 'lucide-react'

interface DecisionBadgeProps {
  granted: boolean
  label?: string
}

/** Complete class strings per state: nothing is concatenated at runtime. */
const DECISION_BADGE = {
  granted: 'badge badge-success gap-1 whitespace-nowrap',
  refused: 'badge badge-error gap-1 whitespace-nowrap',
}

/**
 * A decision always carries an icon and a word, so the state is never conveyed by
 * colour alone.
 */
export default function DecisionBadge({ granted, label }: DecisionBadgeProps) {
  return (
    <span className={granted ? DECISION_BADGE.granted : DECISION_BADGE.refused}>
      {granted ? (
        <CircleCheck size={12} aria-hidden="true" />
      ) : (
        <CircleX size={12} aria-hidden="true" />
      )}
      {label ?? (granted ? 'Decrypted' : 'Refused')}
    </span>
  )
}
