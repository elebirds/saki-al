import React from 'react'
import { Card } from 'antd'

const ProjectWorkspace: React.FC = () => {
  return (
    <Card className="!border-github-border !bg-github-panel">
      <div className="text-sm text-github-muted">
        Workspace will be integrated here. Expect routes like /projects/:id/workspace/:datasetId.
      </div>
    </Card>
  )
}

export default ProjectWorkspace
