import type { EvidenceStep } from '@/lib/types'

export function EvidenceTable({ steps }: { steps: EvidenceStep[] }) {
  if (!steps.length) return <p className="text-sm text-muted-foreground">No right-sizing steps were recorded for this instance.</p>
  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full text-sm">
        <caption className="sr-only">Pipeline evidence steps</caption>
        <thead className="bg-muted text-left text-xs text-muted-foreground">
          <tr><th scope="col" className="px-3 py-2">Step</th><th scope="col" className="px-3 py-2">Calculation</th><th scope="col" className="px-3 py-2">Result</th></tr>
        </thead>
        <tbody>
          {steps.map((s, i) => (
            <tr key={i} className="border-t">
              <td className="px-3 py-2 font-medium">{s.step}</td>
              <td className="px-3 py-2 font-mono text-xs">{s.calculation}</td>
              <td className={'px-3 py-2 ' + (/rejected|blocked|NOT CHECKED/.test(s.result) ? 'text-warning' : '')}>{s.result}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
