import { Link } from 'react-router'
import { Button } from '@/components/ui/button'

export default function NotFound() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 text-center">
      <p className="text-5xl font-semibold text-muted-foreground">404</p>
      <p>That page doesn't exist.</p>
      <Button asChild><Link to="/">Go home</Link></Button>
    </div>
  )
}
