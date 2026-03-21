package apihttp

import (
	"context"
	"encoding/json"
	"errors"
	"strings"

	authctx "github.com/elebirds/saki/saki-controlplane/internal/app/auth"
	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	assetapp "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/app"
	"github.com/go-faster/jx"
	"github.com/google/uuid"
)

func currentPrincipalID(ctx context.Context) (*uuid.UUID, error) {
	claims, ok := authctx.ClaimsFromContext(ctx)
	if !ok {
		return nil, unauthorized("authentication required")
	}
	// 关键设计：资产写入链路记录的是 principal_id，而不是历史 user_id 字符串别名。
	principalID := claims.PrincipalID
	return &principalID, nil
}

func parseAssetID(raw string) (uuid.UUID, error) {
	assetID, err := uuid.Parse(raw)
	if err != nil {
		return uuid.Nil, errors.New("invalid asset_id")
	}
	return assetID, nil
}

func parseOwnerBinding(req *openapi.AssetUploadInitRequest) (assetapp.DurableOwnerBinding, error) {
	ownerType, err := assetapp.ParseAssetOwnerType(strings.TrimSpace(string(req.GetOwnerType())))
	if err != nil {
		return assetapp.DurableOwnerBinding{}, err
	}
	role, err := assetapp.ParseAssetReferenceRole(strings.TrimSpace(string(req.GetRole())))
	if err != nil {
		return assetapp.DurableOwnerBinding{}, err
	}
	return assetapp.DurableOwnerBinding{
		OwnerType: ownerType,
		OwnerID:   req.GetOwnerID(),
		Role:      role,
		IsPrimary: req.GetIsPrimary(),
	}, nil
}

func requireOwnerWritePermission(ctx context.Context, binding assetapp.DurableOwnerBinding) error {
	claims, ok := authctx.ClaimsFromContext(ctx)
	if !ok {
		return unauthorized("authentication required")
	}
	permission := writePermissionForOwner(binding.OwnerType)
	if permission == "" {
		return accessapp.ErrForbidden
	}
	if !claims.HasPermission(permission) {
		return accessapp.ErrForbidden
	}
	return nil
}

func writePermissionForOwner(ownerType assetapp.AssetOwnerType) string {
	switch ownerType {
	case assetapp.AssetOwnerTypeProject:
		return "projects:write"
	case assetapp.AssetOwnerTypeDataset, assetapp.AssetOwnerTypeSample:
		return "datasets:write"
	default:
		return ""
	}
}

func normalizeKind(raw string) string {
	trimmed := strings.ToLower(strings.TrimSpace(raw))
	if trimmed == "" {
		return ""
	}

	var b strings.Builder
	for _, r := range trimmed {
		switch {
		case r >= 'a' && r <= 'z':
			b.WriteRune(r)
		case r >= '0' && r <= '9':
			b.WriteRune(r)
		case r == '-' || r == '_':
			b.WriteRune(r)
		default:
			b.WriteByte('-')
		}
	}
	return strings.Trim(b.String(), "-")
}

func encodeMetadata(metadata map[string]jx.Raw) ([]byte, error) {
	if len(metadata) == 0 {
		return []byte(`{}`), nil
	}
	encoded := make(map[string]json.RawMessage, len(metadata))
	for key, value := range metadata {
		encoded[key] = json.RawMessage(value)
	}
	return json.Marshal(encoded)
}

func decodeMetadata(raw []byte) (map[string]jx.Raw, error) {
	if len(raw) == 0 {
		return map[string]jx.Raw{}, nil
	}
	decoded := map[string]json.RawMessage{}
	if err := json.Unmarshal(raw, &decoded); err != nil {
		return nil, err
	}
	result := make(map[string]jx.Raw, len(decoded))
	for key, value := range decoded {
		result[key] = jx.Raw(value)
	}
	return result, nil
}
