import { Check, X } from 'lucide-react'
import type { PolicyTreeNode } from '../lib/types.ts'

interface PolicyTraceProps {
  policy: string
  tree?: PolicyTreeNode | null
  showTree?: boolean
}

/**
 * The signature element of the interface: a ciphertext policy rendered as
 * monospace text plus a trace of exactly which of its leaves the caller's
 * attribute set satisfied. A refusal becomes explainable instead of mysterious.
 */

/** Complete class strings per state: no class is assembled at runtime. */
const LEAF_CLASS = {
  held: 'flex flex-wrap items-center gap-1.5 font-mono text-xs text-success',
  missing: 'flex flex-wrap items-center gap-1.5 font-mono text-xs text-error',
}

const OPERATOR_BADGE = {
  met: 'badge badge-xs badge-success',
  unmet: 'badge badge-xs badge-error',
}

function TraceNode({ node }: { node: PolicyTreeNode }) {
  if (node.type === 'attribute' && node.attribute) {
    return (
      <li className={node.satisfied ? LEAF_CLASS.held : LEAF_CLASS.missing}>
        {node.satisfied ? (
          <Check size={12} aria-hidden="true" />
        ) : (
          <X size={12} aria-hidden="true" />
        )}
        <span>{node.attribute}</span>
        <span className="font-sans text-base-content/60">
          {node.satisfied ? 'held' : 'not held'}
        </span>
      </li>
    )
  }

  const operator = node.type === 'and' ? 'AND' : node.type === 'or' ? 'OR' : 'NOT'
  return (
    <li>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className={node.satisfied ? OPERATOR_BADGE.met : OPERATOR_BADGE.unmet}>
          {operator}
        </span>
        <span className="font-mono text-[0.6875rem] uppercase tracking-wide text-base-content/60">
          {node.satisfied ? 'satisfied' : 'not satisfied'}
        </span>
      </div>
      <ul className="mt-1 ml-2 flex flex-col gap-1 border-l border-base-300 pl-3">
        {node.children.map((child, index) => (
          <TraceNode key={`${child.type}-${child.attribute ?? index}`} node={child} />
        ))}
      </ul>
    </li>
  )
}

export default function PolicyTrace({ policy, tree, showTree = true }: PolicyTraceProps) {
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <code className="block max-w-full overflow-x-auto rounded-field border border-base-300 bg-base-200 px-2 py-1.5 font-mono text-xs">
        {policy}
      </code>
      {tree && showTree ? (
        <ul className="flex flex-col gap-1" aria-label="Policy trace">
          <TraceNode node={tree} />
        </ul>
      ) : null}
    </div>
  )
}
