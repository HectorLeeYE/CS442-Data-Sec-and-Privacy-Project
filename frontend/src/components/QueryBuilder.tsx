import { ListFilter, Plus, RefreshCw, Search, X } from 'lucide-react'
import type { DatasetField, QueryFilter, QueryOperator } from '../lib/types.ts'

const OPERATORS: { value: QueryOperator; label: string }[] = [
  { value: 'eq', label: 'equals' },
  { value: 'in', label: 'is one of' },
  { value: 'contains', label: 'contains' },
  { value: 'gte', label: 'at least' },
  { value: 'lte', label: 'at most' },
]

const PAGE_SIZE_OPTIONS = [25, 50, 100]
const PAGE_SIZE_DEFAULT = 25

interface QueryBuilderProps {
  fields: DatasetField[]
  filters: QueryFilter[]
  onFiltersChange: (filters: QueryFilter[]) => void
  selectedFields: string[]
  onSelectedFieldsChange: (fields: string[]) => void
  onRun: () => void
  onReset: () => void
  running: boolean
  disabled: boolean
  /** null means "use the server default", so no radio starts out selected. */
  pageSize: number | null
  onPageSizeChange: (size: number | null) => void
}

function valueToText(value: unknown): string {
  if (value === undefined || value === null) return ''
  return Array.isArray(value) ? value.join(', ') : String(value)
}

/**
 * Query composer. Filters are labelled as running *after* decryption, because a
 * CP-ABE deployment cannot filter ciphertext it may not open.
 */
export default function QueryBuilder({
  fields,
  filters,
  onFiltersChange,
  selectedFields,
  onSelectedFieldsChange,
  onRun,
  onReset,
  running,
  disabled,
  pageSize,
  onPageSizeChange,
}: QueryBuilderProps) {
  const queryable = fields.filter((field) => field.is_queryable)
  const selectable = fields.filter((field) => field.is_selectable)

  const patchFilter = (index: number, patch: Partial<QueryFilter>) => {
    onFiltersChange(
      filters.map((filter, position) => (position === index ? { ...filter, ...patch } : filter)),
    )
  }

  const addFilter = () => {
    onFiltersChange([...filters, { field: queryable[0]?.name ?? '', op: 'eq', value: '' }])
  }

  const removeFilter = (index: number) => {
    onFiltersChange(filters.filter((_filter, position) => position !== index))
  }

  const toggleField = (name: string, checked: boolean) => {
    const next =
      selectedFields.length === 0
        ? selectable.map((field) => field.name)
        : [...selectedFields]
    onSelectedFieldsChange(
      checked ? [...next, name] : next.filter((item) => item !== name),
    )
  }

  return (
    <form
      className="flex min-w-0 flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault()
        onRun()
      }}
    >
      <fieldset className="fieldset min-w-0 gap-2">
        <legend className="fieldset-legend flex items-center gap-2">
          <ListFilter size={14} aria-hidden="true" />
          Filters
        </legend>
        <p className="text-xs text-base-content/60">
          Filters run on the rows your attributes already decrypted. Records you cannot
          decrypt are never filtered on, so a filter can never reveal them.
        </p>

        {filters.length === 0 ? (
          <p className="text-xs text-base-content/60">
            No filters yet: the query returns every row you can decrypt.
          </p>
        ) : null}

        <ul className="flex min-w-0 flex-col gap-2">
          {filters.map((filter, index) => (
            <li
              key={`filter-${index}`}
              className="grid min-w-0 grid-cols-1 gap-2 rounded-field border border-base-300 bg-base-100 p-2 sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)_auto] sm:items-center"
            >
              <select
                className="select select-sm w-full"
                aria-label={`Filter ${index + 1} field`}
                value={filter.field}
                onChange={(event) => patchFilter(index, { field: event.target.value })}
              >
                {queryable.map((field) => (
                  <option key={field.name} value={field.name}>
                    {field.label}
                  </option>
                ))}
              </select>

              <select
                className="select select-sm w-full sm:w-32"
                aria-label={`Filter ${index + 1} operator`}
                value={filter.op}
                onChange={(event) => {
                  const op = event.target.value as QueryOperator
                  patchFilter(index, { op, value: op === 'in' ? [] : '' })
                }}
              >
                {OPERATORS.map((operator) => (
                  <option key={operator.value} value={operator.value}>
                    {operator.label}
                  </option>
                ))}
              </select>

              <input
                className="input input-sm w-full"
                aria-label={`Filter ${index + 1} value`}
                placeholder={filter.op === 'in' ? 'comma separated values' : 'value'}
                value={valueToText(filter.value)}
                onChange={(event) =>
                  patchFilter(index, {
                    value:
                      filter.op === 'in'
                        ? event.target.value
                            .split(',')
                            .map((item) => item.trim())
                            .filter(Boolean)
                        : event.target.value,
                  })
                }
              />

              <button
                type="button"
                className="btn btn-ghost btn-sm btn-square tooltip tooltip-left"
                data-tip="Remove this filter"
                aria-label={`Remove filter ${index + 1}`}
                onClick={() => removeFilter(index)}
              >
                <X size={14} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>

        <button
          type="button"
          className="btn btn-outline btn-sm w-fit"
          onClick={addFilter}
          disabled={queryable.length === 0}
        >
          <Plus size={14} aria-hidden="true" />
          Add filter
        </button>
      </fieldset>

      <fieldset className="fieldset min-w-0 gap-2">
        <legend className="fieldset-legend">Columns returned</legend>
        <p className="text-xs text-base-content/60">
          Direct identifiers are excluded by the dataset definition, so they cannot be
          selected here. Leaving every box clear returns all selectable columns.
        </p>
        <ul className="flex flex-wrap gap-x-4 gap-y-1">
          {selectable.map((field) => (
            <li key={field.name}>
              <label className="label cursor-pointer gap-2">
                <input
                  type="checkbox"
                  className="checkbox checkbox-sm"
                  checked={selectedFields.length === 0 || selectedFields.includes(field.name)}
                  onChange={(event) => toggleField(field.name, event.target.checked)}
                />
                <span className="font-mono text-xs">{field.name}</span>
              </label>
            </li>
          ))}
        </ul>
      </fieldset>

      <div className="flex flex-wrap items-end gap-3">
        <button className="btn btn-primary btn-sm" type="submit" disabled={running || disabled}>
          {running ? (
            <span className="loading loading-spinner loading-xs"></span>
          ) : (
            <Search size={14} aria-hidden="true" />
          )}
          Run query
        </button>
        <button
          className="btn btn-ghost btn-sm"
          type="button"
          onClick={onReset}
          disabled={running}
        >
          <RefreshCw size={14} aria-hidden="true" />
          Clear filters
        </button>
      </div>

      <fieldset className="fieldset min-w-0 gap-2">
        <legend className="fieldset-legend">Results per page</legend>
        <p className="text-xs text-base-content/60">
          Server default is {PAGE_SIZE_DEFAULT} rows. Choosing a size applies to the next run.
        </p>
        <div className="filter" role="group" aria-label="Results per page">
          <input
            className="btn btn-sm filter-reset"
            type="radio"
            name="page-size"
            aria-label="Use the default page size"
            checked={pageSize === null}
            onChange={() => onPageSizeChange(null)}
          />
          {PAGE_SIZE_OPTIONS.map((size) => (
            <input
              key={size}
              className="btn btn-sm"
              type="radio"
              name="page-size"
              aria-label={`${size} rows per page`}
              checked={pageSize === size}
              onChange={() => onPageSizeChange(size)}
            />
          ))}
        </div>
      </fieldset>
    </form>
  )
}
