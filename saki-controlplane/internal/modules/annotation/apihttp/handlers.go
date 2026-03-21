package apihttp

import annotationapp "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/app"

// 关键设计：annotation transport 入口只负责装配。
// 原始 JSON 编解码与 OpenAPI 映射单独放在 codec.go，避免 handler 文件同时承担协议与业务边界。
type Handlers struct {
	create *annotationapp.CreateAnnotationUseCase
	list   *annotationapp.ListAnnotationsUseCase
}

func NewHandlers(samples annotationapp.SampleStore, annotations annotationapp.AnnotationStore, mapper annotationapp.Mapper) *Handlers {
	return NewHandlersWithDependencies(samples, nil, nil, annotations, mapper)
}

func NewHandlersWithDependencies(samples annotationapp.SampleStore, datasets annotationapp.DatasetStore, projects annotationapp.ProjectDatasetStore, annotations annotationapp.AnnotationStore, mapper annotationapp.Mapper) *Handlers {
	return &Handlers{
		create: annotationapp.NewCreateAnnotationUseCase(samples, datasets, projects, annotations, mapper),
		list:   annotationapp.NewListAnnotationsUseCase(samples, projects, annotations),
	}
}
