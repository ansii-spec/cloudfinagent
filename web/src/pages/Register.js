import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/common'

export default function Register() {
  const navigate = useNavigate()
  const [errors, setErrors] = useState({})

  function onSubmit(e) {
    e.preventDefault()
    const f = Object.fromEntries(new FormData(e.currentTarget))
    const next = {}
    if (!f.name.trim()) next.name = 'Enter your full name.'
    if (!/^\S+@\S+\.\S+$/.test(f.email)) next.email = 'Enter a valid work email.'
    if (!f.org.trim()) next.org = 'Enter your organization name.'
    if (f.password.length < 8) next.password = 'Use at least 8 characters.'
    if (f.confirm !== f.password) next.confirm = 'Passwords do not match.'
    setErrors(next)
    if (Object.keys(next).length === 0) navigate('/onboarding/connect')
  }

  return (
    <>
      <h1 className="text-xl font-bold">Create account</h1>
      <form noValidate onSubmit={onSubmit} className="mt-6 space-y-4">
        <Field id="name" name="name" label="Full name" autoComplete="name" error={errors.name} />
        <Field id="email" name="email" type="email" label="Work email" autoComplete="email" error={errors.email} />
        <Field id="org" name="org" label="Organization name" autoComplete="organization" error={errors.org} />
        <Field id="password" name="password" type="password" label="Password" autoComplete="new-password" error={errors.password} />
        <Field id="confirm" name="confirm" type="password" label="Confirm password" autoComplete="new-password" error={errors.confirm} />
        <Button type="submit" size="lg" className="w-full">Register</Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted-foreground">
        Already have an account? <Link to="/login" className="text-primary hover:underline">Log in</Link>
      </p>
    </>
  )
}
