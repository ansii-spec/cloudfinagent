import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/common'

export default function Login() {
  const navigate = useNavigate()
  const [errors, setErrors] = useState({})

  function onSubmit(e) {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    const next = {}
    if (!/^\S+@\S+\.\S+$/.test(form.get('email'))) next.email = 'Enter a valid email address.'
    if (!form.get('password')) next.password = 'Enter your password.'
    setErrors(next)
    if (Object.keys(next).length === 0) navigate('/dashboard')
  }

  return (
    <>
      <h1 className="text-xl font-bold">Log in to your account</h1>
      <p className="mt-1 text-sm text-muted-foreground">Monitor and reduce your AWS spend.</p>
      <form noValidate onSubmit={onSubmit} className="mt-6 space-y-4">
        <Field id="email" name="email" type="email" label="Email" placeholder="name@company.com" autoComplete="email" error={errors.email} />
        <Field id="password" name="password" type="password" label="Password" autoComplete="current-password" error={errors.password} />
        <div className="text-right">
          <a href="#" className="text-sm text-primary hover:underline">Forgot password?</a>
        </div>
        <Button type="submit" size="lg" className="w-full">Log in</Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted-foreground">
        No account? <Link to="/register" className="text-primary hover:underline">Register</Link>
      </p>
    </>
  )
}
