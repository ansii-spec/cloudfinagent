const STEPS = [
  ['You create an IAM role', 'in your AWS account (CloudFormation)'],
  ['You share the Role ARN and External ID', 'identifiers, not secrets'],
  ['We call STS AssumeRole', 'with that ARN and External ID'],
  ['STS checks the trust policy', 'the External ID must match'],
  ['Temporary credentials (1 h)', 'used only for the calls we need'],
]

export function SecurityFlowDiagram() {
  return (
    <ol aria-label="How access works" className="grid gap-px overflow-hidden rounded-md border bg-border sm:grid-cols-5">
      {STEPS.map(([title, body], i) => (
        <li key={title} className="bg-card p-3">
          <p className="text-xs text-muted-foreground">Step {i + 1}</p>
          <p className="mt-1 text-sm font-bold">{title}</p>
          <p className="text-xs text-muted-foreground">{body}</p>
        </li>
      ))}
    </ol>
  )
}
