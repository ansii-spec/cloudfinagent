import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import { BrowserRouter } from 'react-router'
import { Toaster } from 'sonner'
import { ApiError, setUnauthorizedHandler } from '@/api/client'
import { TooltipProvider } from '@/components/ui/tooltip'
import { AppRoutes } from '@/routes'

export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: (n, e) => !(e instanceof ApiError && e.status < 500) && n < 2,
        refetchOnWindowFocus: false,
      },
    },
  })
}

export default function App() {
  const [qc] = useState(makeQueryClient)
  setUnauthorizedHandler(() => qc.setQueryData(['me'], null)) // 401 -> route guard sends the user to /login
  return (
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
        <Toaster richColors position="top-right" />
      </TooltipProvider>
    </QueryClientProvider>
  )
}
