import { Lock, Unlock } from 'lucide-react'
import { useEffect, useRef } from 'react'
import type { DeniedPolicyGroup } from '../lib/types.ts'
import AttributeChips from './AttributeChips.tsx'

interface WhyDeniedDialogProps {
  group: DeniedPolicyGroup | null
  attributes: string[]
  onClose: () => void
}

/**
 * Explains one refusal: the ciphertext policy, the attributes it references, which
 * of them the caller holds, and which are missing. Values stay unreachable - the
 * point is to make the *rule* legible, not to leak the data.
 */
export default function WhyDeniedDialog({ group, attributes, onClose }: WhyDeniedDialogProps) {
  const dialogRef = useRef<HTMLDialogElement | null>(null)

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (group && !dialog.open) dialog.showModal()
    if (!group && dialog.open) dialog.close()
  }, [group])

  const held = new Set(attributes)
  const decisionAttributes = group
    ? [...new Set([...group.missing_attributes])].sort()
    : []

  return (
    <dialog id="why-denied" className="modal" ref={dialogRef} onClose={onClose}>
      <div className="modal-box w-11/12 max-w-2xl">
        <h3 className="text-base font-bold">Why this policy refused the records</h3>

        {group ? (
          <div className="flex flex-col gap-3 py-3">
            <code className="block overflow-x-auto rounded-field border border-base-300 bg-base-200 px-2 py-1.5 font-mono text-xs">
              {group.policy}
            </code>

            <p className="text-sm text-base-content/80">{group.reason}</p>

            <dl className="flex flex-col gap-2 text-sm">
              <div className="flex flex-col gap-1">
                <dt className="font-mono text-[0.6875rem] uppercase tracking-wide text-base-content/60">
                  attributes this policy mentions that you are missing
                </dt>
                <dd>
                  {decisionAttributes.length === 0 ? (
                    <span className="text-base-content/60">
                      None: the refusal comes from the shape of the policy itself.
                    </span>
                  ) : (
                    <ul className="flex flex-wrap gap-2">
                      {decisionAttributes.map((attribute) => (
                        <li key={attribute}>
                          <span className="badge badge-sm badge-error gap-1 font-mono">
                            <Lock size={11} aria-hidden="true" />
                            {attribute}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </dd>
              </div>

              <div className="flex flex-col gap-1">
                <dt className="flex items-center gap-1 font-mono text-[0.6875rem] uppercase tracking-wide text-base-content/60">
                  <Unlock size={11} aria-hidden="true" />
                  your current attribute set ({held.size})
                </dt>
                <dd>
                  <AttributeChips attributes={attributes} small />
                </dd>
              </div>
            </dl>

            <p className="text-xs text-base-content/60">
              <strong>{group.count}</strong> record{group.count === 1 ? '' : 's'} stay
              unreadable. In a real CP-ABE deployment the decryption would fail
              cryptographically; here the policy check refuses before any value is read.
            </p>
          </div>
        ) : null}

        <div className="modal-action">
          <form method="dialog">
            <button className="btn btn-sm">Close</button>
          </form>
        </div>
      </div>
      <form method="dialog" className="modal-backdrop">
        <button>close</button>
      </form>
    </dialog>
  )
}
