import React, { useEffect, useState } from 'react'

/** Two independent columns so a short card does not stretch to its neighbor. */
export const Grid: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const items = React.Children.toArray(children)
  const [wide, setWide] = useState(() => window.matchMedia('(min-width: 768px)').matches)
  useEffect(() => {
    const query = window.matchMedia('(min-width: 768px)')
    const apply = () => setWide(query.matches)
    query.addEventListener('change', apply)
    return () => query.removeEventListener('change', apply)
  }, [])
  if (!wide) return <div className="flex flex-col gap-3">{items}</div>
  return (
    <div className="grid grid-cols-2 items-start gap-3">
      <div className="flex flex-col gap-3">{items.filter((_, index) => index % 2 === 0)}</div>
      <div className="flex flex-col gap-3">{items.filter((_, index) => index % 2 === 1)}</div>
    </div>
  )
}

export const Card: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <article aria-label={label} className="flex flex-col gap-2 rounded-card border border-default bg-surface p-4">
    {children}
  </article>
)
