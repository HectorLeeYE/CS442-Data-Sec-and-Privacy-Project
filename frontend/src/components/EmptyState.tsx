import { CircleHelp } from 'lucide-react'
import type { ReactNode } from 'react'

interface EmptyStateProps {
  title: string
  description: string
  action?: ReactNode
  icon?: ReactNode
}

/** Empty states explain the cause and offer the next useful action. */
export default function EmptyState({ title, description, action, icon }: EmptyStateProps) {
  return (
    <div className="card border border-dashed border-base-300 bg-base-100">
      <div className="card-body items-center gap-2 py-10 text-center">
        <span className="text-base-content/50" aria-hidden="true">
          {icon ?? <CircleHelp size={28} />}
        </span>
        <h3 className="card-title text-base">{title}</h3>
        <p className="max-w-prose text-sm text-base-content/70">{description}</p>
        {action ? <div className="card-actions mt-2">{action}</div> : null}
      </div>
    </div>
  )
}
