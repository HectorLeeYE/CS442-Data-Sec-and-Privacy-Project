import { Check, SlidersHorizontal, UserRound, Users } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { formatTimestamp } from '../lib/format.ts'
import type { AdminUser, AdminUserUpdate, UserStatus } from '../lib/types.ts'
import AttributeChips from './AttributeChips.tsx'

interface UserAttributesManagerProps {
  users: AdminUser[]
  assignableAttributes: string[]
  assignableRoles: string[]
  updatingUserId: number | null
  onUpdate: (userId: number, payload: AdminUserUpdate) => Promise<void>
}

/** Complete class strings per state: no class is assembled at runtime. */
const STATUS_BADGE: Record<UserStatus, string> = {
  active: 'badge badge-sm badge-success',
  pending: 'badge badge-sm badge-warning',
  disabled: 'badge badge-sm badge-error',
}

/** Small status indicator; the adjacent badge always states the status in words. */
const STATUS_DOT: Record<UserStatus, string> = {
  active: 'status status-sm status-success',
  pending: 'status status-sm status-warning',
  disabled: 'status status-sm status-error',
}

/**
 * Administrators change an account's attribute set here. That single edit decides
 * which ciphertext policies the account can satisfy on its next request - no data
 * is touched and no session needs to be recreated.
 */
export default function UserAttributesManager({
  users,
  assignableAttributes,
  assignableRoles,
  updatingUserId,
  onUpdate,
}: UserAttributesManagerProps) {
  const [selected, setSelected] = useState<AdminUser | null>(null)

  return (
    <section className="flex min-w-0 flex-col gap-3" aria-labelledby="users-heading">
      <div className="flex items-center gap-2">
        <Users size={16} aria-hidden="true" className="text-secondary" />
        <h3 id="users-heading" className="text-sm font-semibold">
          Accounts and attribute sets
        </h3>
        <span className="badge badge-sm badge-outline">{users.length} accounts</span>
      </div>
      <p className="text-xs text-base-content/60">
        Every account is sample content. Editing an attribute set re-issues that account's
        key material, so its next query is decided by the new set.
      </p>

      <ul className="grid min-w-0 gap-3 xl:grid-cols-2">
        {users.map((user) => (
          <li key={user.id} className="card border border-base-300 bg-base-100">
            <div className="card-body min-w-0 gap-3 p-4">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="flex items-center gap-2">
                  <UserRound size={16} aria-hidden="true" className="text-base-content/60" />
                  <div className="flex flex-col">
                    <span className="text-sm font-semibold">{user.full_name}</span>
                    <span className="font-mono text-xs text-base-content/60">
                      {user.email}
                    </span>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="flex items-center gap-2">
                    <span className={STATUS_DOT[user.status]} aria-hidden="true"></span>
                    <span className={STATUS_BADGE[user.status]}>{user.status}</span>
                  </span>
                  {user.roles.map((role) => (
                    <span key={role} className="badge badge-sm badge-primary font-mono">
                      {role}
                    </span>
                  ))}
                </div>
              </div>

              <AttributeChips
                attributes={user.attributes}
                emptyLabel="No attributes: this account can decrypt nothing."
                small
              />

              <div className="flex flex-wrap gap-2">
                {user.access_preview.map((preview) => (
                  <span
                    key={preview.dataset_slug}
                    className="badge badge-sm badge-outline gap-1 font-mono"
                  >
{preview.dataset_slug}: {preview.granted_count}/{preview.granted_count + preview.denied_count}
                  </span>
                ))}
              </div>

              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-mono text-[0.6875rem] text-base-content/60">
                  last sign-in {formatTimestamp(user.last_login_at)}
                </span>
                <button
                  type="button"
                  className="btn btn-outline btn-sm"
                  onClick={() => setSelected(user)}
                >
                  <SlidersHorizontal size={14} aria-hidden="true" />
                  Edit attributes
                </button>
              </div>
            </div>
          </li>
        ))}
      </ul>

      <EditUserDialog
        key={selected?.id ?? 'none'}
        user={selected}
        assignableAttributes={assignableAttributes}
        assignableRoles={assignableRoles}
        saving={updatingUserId !== null && selected?.id === updatingUserId}
        onClose={() => setSelected(null)}
        onSave={onUpdate}
      />
    </section>
  )
}

interface EditUserDialogProps {
  user: AdminUser | null
  assignableAttributes: string[]
  assignableRoles: string[]
  saving: boolean
  onClose: () => void
  onSave: (userId: number, payload: AdminUserUpdate) => Promise<void>
}

function EditUserDialog({
  user,
  assignableAttributes,
  assignableRoles,
  saving,
  onClose,
  onSave,
}: EditUserDialogProps) {
  const dialogRef = useRef<HTMLDialogElement | null>(null)
  // The dialog is remounted per account (see the `key` prop), so the draft state
  // can be initialized from props instead of being synchronised in an effect.
  const [status, setStatus] = useState<UserStatus>(user?.status ?? 'pending')
  const [roles, setRoles] = useState<string[]>(user?.roles ?? [])
  const [attributes, setAttributes] = useState<string[]>(user?.attributes ?? [])
  const [note, setNote] = useState('')

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (user && !dialog.open) dialog.showModal()
    if (!user && dialog.open) dialog.close()
  }, [user])

  const toggle = (list: string[], value: string, checked: boolean) =>
    checked ? [...list, value] : list.filter((item) => item !== value)

  return (
    <dialog id="edit-user" className="modal" ref={dialogRef} onClose={onClose}>
      <div className="modal-box w-11/12 max-w-3xl">
        <h3 className="text-base font-bold">
          {user ? `Attribute set for ${user.full_name}` : 'Attribute set'}
        </h3>

        {user ? (
          <form
            className="flex flex-col gap-4 py-3"
            onSubmit={async (event) => {
              event.preventDefault()
              await onSave(user.id, {
                status,
                roles,
                attributes,
                note: note.trim() === '' ? undefined : note.trim(),
              })
              onClose()
            }}
          >
            <div className="flex flex-wrap items-end gap-3">
              <div className="flex flex-col gap-1">
                <label className="label font-mono text-[0.6875rem]" htmlFor="edit-status">
                  Account status
                </label>
                <select
                  id="edit-status"
                  className="select select-sm w-40"
                  value={status}
                  onChange={(event) => setStatus(event.target.value as UserStatus)}
                >
                  <option value="active">active</option>
                  <option value="pending">pending</option>
                  <option value="disabled">disabled</option>
                </select>
              </div>
              <div className="flex flex-col gap-1">
                <label className="label font-mono text-[0.6875rem]" htmlFor="edit-note">
                  Change note (kept in the audit trail)
                </label>
                <input
                  id="edit-note"
                  className="input input-sm w-72"
                  placeholder="Why is this attribute set changing?"
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                />
              </div>
            </div>

            <fieldset className="fieldset min-w-0 gap-2">
              <legend className="fieldset-legend">Roles (route-level access)</legend>
              <ul className="flex flex-wrap gap-x-4 gap-y-1">
                {assignableRoles.map((role) => (
                  <li key={role}>
                    <label className="label cursor-pointer gap-2">
                      <input
                        type="checkbox"
                        className="checkbox checkbox-sm"
                        checked={roles.includes(role)}
                        onChange={(event) => setRoles(toggle(roles, role, event.target.checked))}
                      />
                      <span className="font-mono text-xs">{role}</span>
                    </label>
                  </li>
                ))}
              </ul>
            </fieldset>

            <fieldset className="fieldset min-w-0 gap-2">
              <legend className="fieldset-legend">
                Attributes (decide which ciphertext policies this account satisfies)
              </legend>
              <div className="max-h-64 overflow-y-auto rounded-field border border-base-300 bg-base-100 p-3">
                <ul className="grid gap-x-4 gap-y-1 sm:grid-cols-2">
                  {assignableAttributes.map((attribute) => (
                    <li key={attribute}>
                      <label className="label cursor-pointer justify-start gap-2">
                        <input
                          type="checkbox"
                          className="checkbox checkbox-sm"
                          checked={attributes.includes(attribute)}
                          onChange={(event) =>
                            setAttributes(toggle(attributes, attribute, event.target.checked))
                          }
                        />
                        <span className="font-mono text-xs">{attribute}</span>
                      </label>
                    </li>
                  ))}
                </ul>
              </div>
            </fieldset>

            <div className="alert alert-info" role="note">
              <span className="text-xs">
                Saving re-issues the attribute set for <strong>{user.email}</strong>. Its next
                request is evaluated against the new set, so the per-dataset access counts in
                the list change immediately.
              </span>
            </div>

            <div className="modal-action">
              <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>
                Cancel
              </button>
              <button type="submit" className="btn btn-primary btn-sm" disabled={saving}>
                {saving ? (
                  <span className="loading loading-spinner loading-xs"></span>
                ) : (
                  <Check size={14} aria-hidden="true" />
                )}
                Save attribute set
              </button>
            </div>
          </form>
        ) : null}
      </div>
      <form method="dialog" className="modal-backdrop">
        <button>close</button>
      </form>
    </dialog>
  )
}
