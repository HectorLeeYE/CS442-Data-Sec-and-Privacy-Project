import { ShieldAlert, ShieldCheck, ShieldHalf } from 'lucide-react'
import type { Tier } from '../api'

// Tier is always spelled out; colour only supports the label.
const STYLE: Record<Tier, { cls: string; Icon: typeof ShieldCheck }> = {
  RED: { cls: 'badge badge-sm badge-soft badge-error font-mono', Icon: ShieldAlert },
  AMBER: { cls: 'badge badge-sm badge-soft badge-warning font-mono', Icon: ShieldHalf },
  GREEN: { cls: 'badge badge-sm badge-soft badge-success font-mono', Icon: ShieldCheck },
}

export default function TierBadge({ tier }: { tier: Tier }) {
  const { cls, Icon } = STYLE[tier]
  return (
    <span className={cls}>
      <Icon size={12} aria-hidden="true" />
      {tier}
    </span>
  )
}
