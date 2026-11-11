import { PageHeader, SectionCard } from '@/components/common'

export default function Placeholder({ title }) {
  return (
    <>
      <PageHeader title={title} />
      <SectionCard>
        <p className="text-sm text-muted-foreground">This screen is not built yet.</p>
      </SectionCard>
    </>
  )
}
