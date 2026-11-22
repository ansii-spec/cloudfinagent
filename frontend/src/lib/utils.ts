import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function copyText(text: string): Promise<void> {
  return navigator.clipboard?.writeText(text) ?? Promise.resolve()
}
