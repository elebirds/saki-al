package domain

import (
	"encoding/json"
	"time"

	"github.com/google/uuid"
)

type InitializationState string

const (
	InitializationStateUninitialized InitializationState = "uninitialized"
	InitializationStateInitialized   InitializationState = "initialized"
)

// 关键设计：identity / authorization / system 三层分别承载“主体与凭据”“权限归属”“初始化态与系统设置”。
// 这样 setup、auth、rbac 可以沿稳定边界演进，避免重新回到旧 saki-api 中身份、授权、系统状态相互缠绕的结构。
type Installation struct {
	ID                       uuid.UUID
	InstallationKey          string
	InitializationState      InitializationState
	Metadata                 json.RawMessage
	InitializedAt            *time.Time
	InitializedByPrincipalID *uuid.UUID
	CreatedAt                time.Time
	UpdatedAt                time.Time
}
