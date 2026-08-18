import { createContext, useContext, useState, type ReactNode } from 'react'

const STORAGE_KEY = 'payguard_api_key'

interface AuthContextValue {
  apiKey: string | null
  connect: (apiKey: string) => void
  disconnect: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [apiKey, setApiKey] = useState<string | null>(() => localStorage.getItem(STORAGE_KEY))

  function connect(key: string) {
    localStorage.setItem(STORAGE_KEY, key)
    setApiKey(key)
  }

  function disconnect() {
    localStorage.removeItem(STORAGE_KEY)
    setApiKey(null)
  }

  return <AuthContext.Provider value={{ apiKey, connect, disconnect }}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
