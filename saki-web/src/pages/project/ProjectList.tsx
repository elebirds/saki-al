import React, { useCallback } from 'react'
import { Card, Tag, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import { api } from '../../services/api'
import { PaginatedList } from '../../components/common/PaginatedList'
import { Project } from '../../types'

const { Title, Text } = Typography

const taskTypeLabel: Record<string, string> = {
  classification: 'Classification',
  detection: 'Detection',
  segmentation: 'Segmentation',
}

const statusLabel: Record<string, string> = {
  active: 'Active',
  archived: 'Archived',
}

const ProjectList: React.FC = () => {
  const navigate = useNavigate()
  const fetchProjects = useCallback(
    (page: number, pageSize: number) => api.getProjects(page, pageSize),
    []
  )

  return (
    <div className="flex h-full flex-col">
      <div className="mb-4 flex items-center justify-between">
        <Title level={3} className="!mb-0">Projects</Title>
      </div>

      <div className="flex-1 overflow-hidden">
        <PaginatedList<Project>
          fetchData={fetchProjects}
          initialPageSize={12}
          pageSizeOptions={['8', '12', '20', '32', '50']}
          renderItems={(items) => (
            <div className="grid gap-4">
              {items.map((project) => (
                <Card
                  key={project.id}
                  className="!border-github-border !bg-github-panel hover:!border-github-border-muted"
                  onClick={() => navigate(`/projects/${project.id}`)}
                >
                  <div className="flex flex-wrap items-center justify-between gap-4">
                    <div>
                      <div className="text-base font-semibold text-github-text">{project.name}</div>
                      {project.description && (
                        <Text type="secondary" className="text-sm">
                          {project.description}
                        </Text>
                      )}
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <Tag color="blue">{taskTypeLabel[project.taskType] || project.taskType}</Tag>
                      <Tag color={project.status === 'active' ? 'green' : 'default'}>
                        {statusLabel[project.status] || project.status}
                      </Tag>
                    </div>
                  </div>
                  <div className="mt-4 grid grid-cols-2 gap-4 text-xs text-github-muted sm:grid-cols-4">
                    <div>
                      <div className="text-github-text font-semibold">{project.datasetCount}</div>
                      <div>Datasets</div>
                    </div>
                    <div>
                      <div className="text-github-text font-semibold">{project.labelCount}</div>
                      <div>Labels</div>
                    </div>
                    <div>
                      <div className="text-github-text font-semibold">{project.branchCount}</div>
                      <div>Branches</div>
                    </div>
                    <div>
                      <div className="text-github-text font-semibold">{project.commitCount}</div>
                      <div>Commits</div>
                    </div>
                  </div>
                </Card>
              ))}
            </div>
          )}
        />
      </div>
    </div>
  )
}

export default ProjectList
