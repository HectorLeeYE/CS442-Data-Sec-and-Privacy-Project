import { Fingerprint } from 'lucide-react'
import { CLASSIFICATION_META, RULE_LABEL } from '../lib/format.ts'
import type { DatasetField } from '../lib/types.ts'

/**
 * The anonymization treatment of every field in a dataset: classification (how
 * identifying it is) and the transform the anonymization phase will apply. The
 * transforms themselves are not implemented yet, so nothing here claims they are.
 */
export default function FieldInventory({ fields }: { fields: DatasetField[] }) {
  return (
    <section className="flex flex-col gap-3" aria-labelledby="field-inventory-heading">
      <div className="flex items-center gap-2">
        <Fingerprint size={16} aria-hidden="true" className="text-primary" />
        <h3 id="field-inventory-heading" className="text-sm font-semibold">
          Field classification ({fields.length})
        </h3>
      </div>
      <p className="text-xs text-base-content/60">
        Classification decides how a field is anonymized. Values already present are
        pre-generalized sample data; the transformation pipeline is planned, not built.
      </p>
      <ul className="flex min-w-0 flex-col gap-1.5">
        {fields.map((field) => {
          const meta = CLASSIFICATION_META[field.classification]
          return (
            <li
              key={field.name}
              className="flex min-w-0 flex-wrap items-center gap-2 rounded-field border border-base-300 bg-base-100 px-2 py-1.5"
            >
              <span className="font-mono text-xs">{field.name}</span>
              <span className={meta.badge}>{meta.label}</span>
              <span className="badge badge-sm badge-outline font-mono">
                {RULE_LABEL[field.anonymization_rule]}
              </span>
              {field.is_selectable ? null : (
                <span className="badge badge-sm badge-ghost">not in results</span>
              )}
              <span className="min-w-0 flex-1 text-xs text-base-content/60">
                {field.description}
              </span>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
