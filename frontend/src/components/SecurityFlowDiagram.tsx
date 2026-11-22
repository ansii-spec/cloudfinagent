import { ArrowRight, KeyRound, Server, ShieldCheck, Timer, UserCog } from 'lucide-react'

const STEPS = [
  { icon: UserCog, title: 'You create an IAM role', body: 'in your own AWS account (CloudFormation)' },
  { icon: KeyRound, title: 'You share Role ARN + External ID', body: 'identifiers, not secrets — no access keys' },
  { icon: Server, title: 'We call STS AssumeRole', body: 'with your role ARN and External ID' },
  { icon: ShieldCheck, title: 'STS validates the trust', body: 'trust policy + External ID must match' },
  { icon: Timer, title: 'Temporary credentials (~1 h)', body: 'used only for the API calls we need' },
]

export function SecurityFlowDiagram() {
  return (
    <ol aria-label="How secure access works" className="grid gap-2 sm:grid-cols-5">
      {STEPS.map((s, i) => (
        <li key={s.title} className="relative flex flex-col items-center gap-1 rounded-md border bg-card p-3 text-center">
          <span className="flex size-9 items-center justify-center rounded-full bg-accent text-accent-foreground"><s.icon className="size-4" aria-hidden="true" /></span>
          <span className="text-xs font-semibold">{i + 1}. {s.title}</span>
          <span className="text-[11px] text-muted-foreground">{s.body}</span>
          {i < STEPS.length - 1 && (
            <ArrowRight aria-hidden="true" className="absolute top-1/2 -right-3 hidden size-4 -translate-y-1/2 text-muted-foreground sm:block" />
          )}
        </li>
      ))}
    </ol>
  )
}
