import { Database } from 'lucide-react'
import type { DatasetSummary } from '../lib/types.ts'

interface DatasetPickerProps {
  datasets: DatasetSummary[]
  value: number | null
  onChange: (datasetId: number) => void
  disabled?: boolean
}

/**
 * Dataset choice. Each option states how much of the dataset the current
 * attribute set can decrypt, so the CP-ABE effect is visible before querying.
 */
export default function DatasetPicker({
  datasets,
  value,
  onChange,
  disabled = false,
}: DatasetPickerProps) {
  const selected = datasets.find((dataset) => dataset.id === value) ?? null

  return (
    <div className="flex min-w-0 flex-col gap-2">
      <label className="label text-xs font-medium" htmlFor="dataset-picker">
        <Database size={14} aria-hidden="true" />
        Dataset
      </label>
      <select
        id="dataset-picker"
        className="select select-sm w-full max-w-md"
        disabled={disabled || datasets.length === 0}
        value={value ?? ''}
        onChange={(event) => onChange(Number(event.target.value))}
      >
        {datasets.length === 0 ? <option value="">No datasets available</option> : null}
        {datasets.map((dataset) => (
          <option key={dataset.id} value={dataset.id}>
            {dataset.name} — {dataset.granted_count} of {dataset.record_count} readable
          </option>
        ))}
      </select>
      {selected ? (
        <div className="flex min-w-0 flex-col gap-1">
          <p className="text-xs text-base-content/70">{selected.description}</p>
          <div className="flex flex-wrap items-center gap-2">
            <span className="badge badge-sm badge-success gap-1">
              {selected.granted_count} decryptable
            </span>
            <span className="badge badge-sm badge-error gap-1">
              {selected.denied_count} refused
            </span>
            <span className="font-mono text-[0.6875rem] text-base-content/60">
              {selected.record_count} records · {selected.field_count} fields ·{' '}
              {selected.policies.length} policies
            </span>
          </div>
        </div>
      ) : null}
    </div>
  )
}
