package apihttp

import (
	datasetapp "github.com/elebirds/saki/saki-controlplane/internal/modules/dataset/app"
)

// 关键设计：transport 装配层只保留用例依赖与构造。
// 请求解析、错误翻译、OpenAPI 映射分别拆到独立文件，避免 handlers.go 再次膨胀成杂糅入口。
type Handlers struct {
	create *datasetapp.CreateDatasetUseCase
	list   *datasetapp.ListDatasetsUseCase
	get    *datasetapp.GetDatasetUseCase
	update *datasetapp.UpdateDatasetUseCase
	delete *datasetapp.DeleteDatasetUseCase
	sample *datasetapp.DeleteSampleUseCase
}

type Dependencies struct {
	Store        datasetapp.Store
	Delete       *datasetapp.DeleteDatasetUseCase
	DeleteSample *datasetapp.DeleteSampleUseCase
}

func NewHandlers(store datasetapp.Store) *Handlers {
	return NewHandlersWithDependencies(Dependencies{Store: store})
}

func NewHandlersWithDependencies(deps Dependencies) *Handlers {
	deleteUseCase := deps.Delete
	if deleteUseCase == nil {
		deleteUseCase = datasetapp.NewDeleteDatasetUseCase(deps.Store)
	}
	return &Handlers{
		create: datasetapp.NewCreateDatasetUseCase(deps.Store),
		list:   datasetapp.NewListDatasetsUseCase(deps.Store),
		get:    datasetapp.NewGetDatasetUseCase(deps.Store),
		update: datasetapp.NewUpdateDatasetUseCase(deps.Store),
		delete: deleteUseCase,
		sample: deps.DeleteSample,
	}
}
