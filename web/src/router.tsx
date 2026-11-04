import { useSyncExternalStore, type AnchorHTMLAttributes, type MouseEvent } from 'react'

/** A very small router: the app has a handful of pages, so no library is needed. */

const listeners = new Set<() => void>()

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  window.addEventListener('popstate', listener)
  return () => {
    listeners.delete(listener)
    window.removeEventListener('popstate', listener)
  }
}

export function navigate(path: string): void {
  if (path === window.location.pathname) return
  window.history.pushState(null, '', path)
  listeners.forEach((listener) => listener())
  window.scrollTo?.(0, 0)
}

export function usePath(): string {
  return useSyncExternalStore(subscribe, () => window.location.pathname)
}

type LinkProps = AnchorHTMLAttributes<HTMLAnchorElement> & { to: string }

export function Link({ to, onClick, ...rest }: LinkProps) {
  const path = usePath()
  const handle = (event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event)
    if (event.defaultPrevented || event.button !== 0) return
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    event.preventDefault()
    navigate(to)
  }
  return (
    <a href={to} aria-current={path === to ? 'page' : undefined} onClick={handle} {...rest} />
  )
}
