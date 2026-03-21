package apihttp

import (
	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	systemapp "github.com/elebirds/saki/saki-controlplane/internal/modules/system/app"
	systemdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/system/domain"
)

func mapInitializationState(value systemdomain.InitializationState) openapi.SystemStatusResponseInitializationState {
	// 关键设计：公开 API 只暴露 initialization 语义，
	// `/system/status` 与 `/system/init` 因此共享同一套词汇，不再外泄 install/setup 历史命名。
	switch value {
	case systemdomain.InitializationStateInitialized:
		return openapi.SystemStatusResponseInitializationStateInitialized
	default:
		return openapi.SystemStatusResponseInitializationStateUninitialized
	}
}

func mapTypeInfo(item systemapp.TypeInfo) openapi.SystemTypeInfo {
	return openapi.SystemTypeInfo{
		Value:                  item.Value,
		Label:                  item.Label,
		Description:            item.Description,
		Color:                  item.Color,
		Enabled:                item.Enabled,
		AllowedAnnotationTypes: append([]string(nil), item.AllowedAnnotationTypes...),
		MustAnnotationTypes:    append([]string(nil), item.MustAnnotationTypes...),
		BannedAnnotationTypes:  append([]string(nil), item.BannedAnnotationTypes...),
	}
}
