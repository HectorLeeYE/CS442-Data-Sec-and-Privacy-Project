import { attributeBadgeClass } from '../lib/format.ts'

interface AttributeChipsProps {
  attributes: string[]
  emptyLabel?: string
  small?: boolean
}

/**
 * The attribute set that record policies are evaluated against. Attributes are
 * shown in monospace with a per-category badge colour so the `category:value`
 * structure of a CP-ABE attribute is visible at a glance.
 */
export default function AttributeChips({
  attributes,
  emptyLabel = 'No attributes assigned to this account.',
  small = false,
}: AttributeChipsProps) {
  if (attributes.length === 0) {
    return <p className="text-sm text-base-content/60">{emptyLabel}</p>
  }

  return (
    <ul className="flex flex-wrap gap-2" aria-label="Attribute set">
      {attributes.map((attribute) => (
        <li key={attribute}>
          <span className={attributeBadgeClass(attribute, small)}>{attribute}</span>
        </li>
      ))}
    </ul>
  )
}
