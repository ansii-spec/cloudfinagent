import { Loader2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { useRegister } from '@/api/hooks'
import { Button } from '@/components/ui/button'
import { FieldError, Input, Label } from '@/components/ui/input'
import { AuthLayout } from './AuthLayout'
import { EMAIL_RE } from './Login'

export default function Register() {
  const navigate = useNavigate()
  const register = useRegister()
  const [f, setF] = useState({ name: '', email: '', password: '' })
  const [touched, setTouched] = useState(false)
  const errs = {
    name: touched && !f.name.trim() ? 'Enter your name' : undefined,
    email: touched && !EMAIL_RE.test(f.email) ? 'Enter a valid email address' : undefined,
    password: touched && f.password.length < 10 ? 'At least 10 characters' : undefined,
  }
  const submit = (e: FormEvent) => {
    e.preventDefault()
    setTouched(true)
    if (!f.name.trim() || !EMAIL_RE.test(f.email) || f.password.length < 10) return
    register.mutate(f, { onSuccess: () => navigate('/connect', { replace: true }) })
  }
  return (
    <AuthLayout title="Create your account" subtitle="No AWS keys needed: connect with a secure read-only role.">
      <form onSubmit={submit} className="space-y-4" noValidate>
        {(['name', 'email', 'password'] as const).map((k) => (
          <div key={k} className="space-y-1.5">
            <Label htmlFor={k}>{k === 'name' ? 'Name' : k === 'email' ? 'Email' : 'Password'}</Label>
            <Input id={k} type={k === 'password' ? 'password' : k === 'email' ? 'email' : 'text'}
              autoComplete={k === 'password' ? 'new-password' : k} value={f[k]}
              onChange={(e) => setF({ ...f, [k]: e.target.value })} aria-invalid={!!errs[k]} />
            <FieldError>{errs[k]}</FieldError>
          </div>
        ))}
        <FieldError>{register.error?.message}</FieldError>
        <Button type="submit" size="lg" className="w-full" disabled={register.isPending}>{register.isPending && <Loader2 className="animate-spin" />}Create account</Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted-foreground">Already registered? <Link to="/login" className="text-primary hover:underline">Log in</Link></p>
    </AuthLayout>
  )
}
