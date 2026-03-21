package apihttp

import projectapp "github.com/elebirds/saki/saki-controlplane/internal/modules/project/app"

// 关键设计：这里仅负责组装 project 模块对外暴露的 use case。
// 参数解析与响应映射属于 transport 边界细节，拆分后各自收敛，避免代理入口继续承担杂项逻辑。
type Handlers struct {
	create             *projectapp.CreateProjectUseCase
	list               *projectapp.ListProjectsUseCase
	get                *projectapp.GetProjectUseCase
	linkDatasets       *projectapp.LinkProjectDatasetsUseCase
	unlinkDatasets     *projectapp.UnlinkProjectDatasetsUseCase
	listDatasetIDs     *projectapp.ListProjectDatasetIDsUseCase
	listDatasetDetails *projectapp.ListProjectDatasetDetailsUseCase
}

func NewHandlers(projects projectapp.Store, datasets projectapp.DatasetStore) *Handlers {
	return &Handlers{
		create:             projectapp.NewCreateProjectUseCase(projects),
		list:               projectapp.NewListProjectsUseCase(projects),
		get:                projectapp.NewGetProjectUseCase(projects),
		linkDatasets:       projectapp.NewLinkProjectDatasetsUseCase(projects, datasets),
		unlinkDatasets:     projectapp.NewUnlinkProjectDatasetsUseCase(projects),
		listDatasetIDs:     projectapp.NewListProjectDatasetIDsUseCase(projects),
		listDatasetDetails: projectapp.NewListProjectDatasetDetailsUseCase(projects, datasets),
	}
}
