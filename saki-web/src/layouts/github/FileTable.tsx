import React from 'react'

export type FileTableProps = {
  header?: React.ReactNode
  children: React.ReactNode
}

export const FileTable: React.FC<FileTableProps> = ({ header, children }) => {
  return (
    <div className="border border-github-border rounded-md overflow-hidden bg-github-panel">
      {header ? (
        <div className="flex items-center justify-between bg-github-base px-4 py-3 border-b border-github-border">
          {header}
        </div>
      ) : null}
      <div className="bg-github-panel">{children}</div>
    </div>
  )
}
