import { Button } from '@/components/ui/button'

function App() {
  return (
    <main className="flex min-h-svh flex-col items-center justify-center gap-4 p-4">
      <h1 className="text-2xl font-semibold">CloudFinAgent</h1>
      <p className="text-muted-foreground">Find and fix wasted AWS spend.</p>
      <Button>Get started</Button>
    </main>
  )
}

export default App
