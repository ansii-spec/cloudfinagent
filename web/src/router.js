import { createBrowserRouter, Navigate } from 'react-router'
import AppShell from '@/components/layout/AppShell'
import AuthLayout from '@/components/layout/AuthLayout'
import Login from '@/pages/Login'
import Register from '@/pages/Register'
import Dashboard from '@/pages/Dashboard'
import Placeholder from '@/pages/Placeholder'

export const router = createBrowserRouter([
  { path: '/', element: <Navigate to="/login" replace /> },
  {
    element: <AuthLayout />,
    children: [
      { path: '/login', element: <Login /> },
      { path: '/register', element: <Register /> },
      { path: '/onboarding/connect', element: <Placeholder title="Connect AWS account" /> },
      { path: '/onboarding/analysis', element: <Placeholder title="Initial analysis" /> },
    ],
  },
  {
    element: <AppShell />,
    children: [
      { path: '/dashboard', element: <Dashboard /> },
      { path: '/suggestions', element: <Placeholder title="Suggestions" /> },
      { path: '/resources', element: <Placeholder title="Resources" /> },
      { path: '/resources/:id', element: <Placeholder title="Resource detail" /> },
      { path: '/actions', element: <Placeholder title="Actions" /> },
      { path: '/settings', element: <Placeholder title="Settings" /> },
    ],
  },
  { path: '*', element: <Navigate to="/dashboard" replace /> },
])
