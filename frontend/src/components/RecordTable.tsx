import { ChevronDown } from 'lucide-react'
import { Fragment, useState } from 'react'
import { formatValue, shortHash } from '../lib/format.ts'
import type { QueryRow } from '../lib/types.ts'
import DecisionBadge from './DecisionBadge.tsx'
import PolicyTrace from './PolicyTrace.tsx'

interface RecordTableProps {
  rows: QueryRow[]
  columns: string[]
}

/**
 * Decrypted rows. Each row keeps its ciphertext policy next to its values, and the
 * detail row shows the full policy trace plus the ciphertext metadata, so the link
 * between "this value" and "this access rule" is never hidden.
 */
export default function RecordTable({ rows, columns }: RecordTableProps) {
  const [expanded, setExpanded] = useState<string | null>(null)

  return (
    <div className="max-w-full min-w-0 overflow-x-auto rounded-box border border-base-300 bg-base-100">
      <table className="table table-sm table-zebra">
        <caption className="sr-only">
          Decrypted records with the ciphertext policy that granted access to each one.
        </caption>
        <thead>
          <tr>
            <th scope="col">Record key</th>
            {columns.map((column) => (
              <th key={column} scope="col" className="font-mono text-xs">
                {column}
              </th>
            ))}
            <th scope="col">Decision</th>
            <th scope="col">
              <span className="sr-only">Policy detail</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const isOpen = expanded === row.record_key
            return (
              <Fragment key={row.record_key}>
                <tr className="hover:bg-base-300">
                  <th scope="row" className="font-mono text-xs whitespace-nowrap">
                    {row.record_key}
                  </th>
                  {columns.map((column) => (
                    <td key={column} className="tabular-nums">
                      {formatValue(row.values[column])}
                    </td>
                  ))}
                  <td>
                    <DecisionBadge granted={row.decision.granted} />
                  </td>
                  <td>
                    <button
                      type="button"
                      className="btn btn-ghost btn-xs"
                      aria-expanded={isOpen}
                      onClick={() => setExpanded(isOpen ? null : row.record_key)}
                    >
                      <ChevronDown
                        size={14}
                        aria-hidden="true"
                        className={isOpen ? 'rotate-180' : undefined}
                      />
                      {isOpen ? 'Hide' : 'Policy'}
                    </button>
                  </td>
                </tr>
                {isOpen ? (
                  <tr>
                    <td colSpan={columns.length + 3} className="bg-base-200">
                      <div className="grid gap-3 p-2 lg:grid-cols-2">
                        <PolicyTrace policy={row.policy} tree={row.policy_tree} />
                        <dl className="flex flex-col gap-1 font-mono text-xs">
                          <div className="flex flex-wrap gap-2">
                            <dt className="text-base-content/60">backend</dt>
                            <dd>{row.ciphertext.backend}</dd>
                            <dt className="text-base-content/60">encrypted</dt>
                            <dd>{row.ciphertext.encrypted ? 'yes' : 'no (placeholder)'}</dd>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <dt className="text-base-content/60">policy hash</dt>
                            <dd>{shortHash(row.ciphertext.policy_hash, 24)}</dd>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <dt className="text-base-content/60">ciphertext</dt>
                            <dd className="break-all">{row.ciphertext.preview}</dd>
                          </div>
                          <div className="flex flex-wrap gap-2 font-sans">
                            <dt className="text-base-content/60">reason</dt>
                            <dd>{row.decision.reason}</dd>
                          </div>
                        </dl>
                      </div>
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
