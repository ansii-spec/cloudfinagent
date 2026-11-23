import { Loader2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { useLogin } from '@/api/hooks'
import { Button } from '@/components/ui/button'
import { FieldError, Input, Label, PasswordInput } from '@/components/ui/input'
import { AuthLayout } from './AuthLayout'

export const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export default function Login() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const login = useLogin()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [touched, setTouched] = useState(false)
  const emailErr = touched && !EMAIL_RE.test(email) ? 'Enter a valid email address' : undefined

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setTouched(true)
    if (!EMAIL_RE.test(email) || !password) return
    login.mutate({ email, password }, { onSuccess: () => navigate(params.get('next') || '/', { replace: true }) })
  }
  return (
    <AuthLayout title="Log in to your account" subtitle="Monitor and reduce your AWS spend.">
      <form onSubmit={submit} className="space-y-4" noValidate>
        <div className="space-y-1.5">
          <Label htmlFor="email">Email</Label>
          <Input id="email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} aria-invalid={!!emailErr} />
          <FieldError>{emailErr}</FieldError>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="password">Password</Label>
          <PasswordInput id="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        <FieldError>{login.error?.message}</FieldError>
        <Button type="submit" size="lg" className="w-full" disabled={login.isPending}>{login.isPending && <Loader2 className="animate-spin" />}Log in</Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted-foreground">No account? <Link to="/register" className="text-primary hover:underline">Create one</Link></p>
    </AuthLayout>
  )
}
