import React from 'react'

const PageHeader: React.FC<{ children: React.ReactNode; className?: string }> = ({ children, className = '' }) => (
  <header data-page-header className={`shrink-0 border-b border-default px-4 sm:px-6 pt-5 pb-3 ${className}`}>
    {children}
  </header>
)

export default PageHeader
