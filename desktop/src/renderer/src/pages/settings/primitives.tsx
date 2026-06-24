import React, { useState, useEffect, useRef } from 'react'
import { ChevronDown } from 'lucide-react'
import { t } from '../../i18n'

// Shared presentational building blocks for the settings tabs.

export const Card: React.FC<{ icon: React.ReactNode; title: string; subtitle?: string; children: React.ReactNode }> = ({
  icon,
  title,
  subtitle,
  children,
}) => (
  <div className="rounded-card border border-default bg-surface p-5">
    <div className="flex items-center gap-2.5 mb-4">
      <div className="w-8 h-8 rounded-lg bg-accent-soft text-accent flex items-center justify-center">{icon}</div>
      <div>
        <h3 className="font-semibold text-content leading-tight">{title}</h3>
        {subtitle && <p className="text-xs text-content-tertiary mt-0.5">{subtitle}</p>}
      </div>
    </div>
    {children}
  </div>
)

export const Field: React.FC<{ label: string; hint?: string; children: React.ReactNode }> = ({
  label,
  hint,
  children,
}) => (
  <div>
    <label className="block text-sm font-medium text-content-secondary mb-1.5">{label}</label>
    {children}
    {hint && <p className="text-xs text-content-tertiary mt-1">{hint}</p>}
  </div>
)

export interface DropdownOption {
  value: string
  label: string
  hint?: string
}

export const Dropdown: React.FC<{
  value: string
  display?: string
  placeholder?: string
  options: DropdownOption[]
  disabled?: boolean
  onChange: (val: string) => void
}> = ({ value, display, placeholder, options, disabled, onChange }) => {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])
  const current = display ?? options.find((o) => o.value === value)?.label ?? ''
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        disabled={disabled}
        onClick={() => !disabled && setOpen((v) => !v)}
        className={`w-full flex items-center justify-between px-3 py-2 rounded-btn border bg-inset text-sm transition-colors ${
          disabled
            ? 'border-default text-content-tertiary cursor-not-allowed opacity-70'
            : 'border-strong text-content cursor-pointer hover:border-accent'
        }`}
      >
        <span className={`truncate ${current ? '' : 'text-content-tertiary'}`}>{current || placeholder || '--'}</span>
        <ChevronDown size={15} className={`text-content-tertiary transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="absolute z-30 mt-1 w-full max-h-64 overflow-y-auto rounded-btn border border-default bg-elevated shadow-lg py-1">
          {options.length === 0 && (
            <div className="px-3 py-2 text-sm text-content-tertiary">{t('models_no_options')}</div>
          )}
          {options.map((o) => (
            <div
              key={o.value}
              onClick={() => {
                onChange(o.value)
                setOpen(false)
              }}
              className={`px-3 py-2 text-sm cursor-pointer transition-colors ${
                o.value === value ? 'bg-accent-soft text-accent' : 'text-content-secondary hover:bg-surface-2'
              }`}
            >
              <div className="truncate">{o.label}</div>
              {o.hint && <div className="text-xs text-content-tertiary mt-0.5 truncate">{o.hint}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export const Toggle: React.FC<{ checked: boolean; onChange: (v: boolean) => void }> = ({ checked, onChange }) => (
  <button
    type="button"
    role="switch"
    aria-checked={checked}
    onClick={() => onChange(!checked)}
    className={`relative inline-flex h-5 w-9 flex-shrink-0 items-center rounded-full transition-colors cursor-pointer ${
      checked ? 'bg-accent' : 'bg-surface-2 border border-strong'
    }`}
  >
    <span
      className={`inline-block h-3.5 w-3.5 rounded-full bg-white shadow transition-transform ${
        checked ? 'translate-x-[18px]' : 'translate-x-[3px]'
      }`}
    />
  </button>
)

export const TextInput: React.FC<React.InputHTMLAttributes<HTMLInputElement>> = (props) => (
  <input
    {...props}
    className={`w-full px-3 py-2 rounded-btn border border-strong bg-inset text-sm text-content placeholder:text-content-tertiary focus:outline-none focus:border-accent transition-colors ${
      props.className || ''
    }`}
  />
)

export const SaveRow: React.FC<{ status: string; onSave: () => void; label?: string }> = ({
  status,
  onSave,
  label,
}) => (
  <div className="flex items-center justify-end gap-3 pt-1">
    <span className={`text-xs text-accent transition-opacity ${status ? 'opacity-100' : 'opacity-0'}`}>{status}</span>
    <button
      onClick={onSave}
      className="px-4 py-2 rounded-btn bg-accent text-accent-contrast hover:bg-accent-hover text-sm font-medium cursor-pointer transition-colors"
    >
      {label ?? t('config_save')}
    </button>
  </div>
)

export const MASK_RE = /[*•]/

export const Modal: React.FC<{
  open: boolean
  title: string
  onClose: () => void
  children: React.ReactNode
  footer?: React.ReactNode
}> = ({ open, title, onClose, children, footer }) => {
  if (!open) return null
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="w-full max-w-md rounded-card border border-default bg-elevated shadow-xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-default">
          <h3 className="font-semibold text-content">{title}</h3>
          <button
            onClick={onClose}
            className="text-content-tertiary hover:text-content cursor-pointer text-lg leading-none px-1"
          >
            ×
          </button>
        </div>
        <div className="px-5 py-4 space-y-4 max-h-[60vh] overflow-y-auto">{children}</div>
        {footer && <div className="flex items-center justify-end gap-2 px-5 py-3.5 border-t border-default">{footer}</div>}
      </div>
    </div>
  )
}

export const Btn: React.FC<
  React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'ghost' | 'danger' }
> = ({ variant = 'ghost', className, children, ...props }) => {
  const styles =
    variant === 'primary'
      ? 'bg-accent text-accent-contrast hover:bg-accent-hover'
      : variant === 'danger'
        ? 'bg-danger-soft text-danger hover:bg-danger/15 border border-danger-border'
        : 'border border-strong text-content-secondary hover:bg-surface-2'
  return (
    <button
      {...props}
      className={`px-4 py-2 rounded-btn text-sm font-medium cursor-pointer transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${styles} ${className || ''}`}
    >
      {children}
    </button>
  )
}
