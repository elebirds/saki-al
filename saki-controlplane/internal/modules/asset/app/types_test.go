package app

import (
	"errors"
	"reflect"
	"testing"

	"github.com/google/uuid"
)

func TestAssetTypedEnumConstantsExposeStrongTypes(t *testing.T) {
	if got, want := reflect.TypeOf(AssetStatusPendingUpload), reflect.TypeOf(AssetStatus("")); got != want {
		t.Fatalf("AssetStatusPendingUpload type got %v want %v", got, want)
	}
	if got, want := reflect.TypeOf(AssetStatusReady), reflect.TypeOf(AssetStatus("")); got != want {
		t.Fatalf("AssetStatusReady type got %v want %v", got, want)
	}
	if got, want := reflect.TypeOf(AssetStorageBackendMinio), reflect.TypeOf(AssetStorageBackend("")); got != want {
		t.Fatalf("AssetStorageBackendMinio type got %v want %v", got, want)
	}
	if got, want := reflect.TypeOf(AssetReferenceRoleAttachment), reflect.TypeOf(AssetReferenceRole("")); got != want {
		t.Fatalf("AssetReferenceRoleAttachment type got %v want %v", got, want)
	}
}

func TestOwnerTypeRolePrimaryValidation(t *testing.T) {
	validCases := []DurableOwnerBinding{
		{
			OwnerType: AssetOwnerTypeProject,
			OwnerID:   uuid.New(),
			Role:      AssetReferenceRoleAttachment,
			IsPrimary: false,
		},
		{
			OwnerType: AssetOwnerTypeProject,
			OwnerID:   uuid.New(),
			Role:      AssetReferenceRoleAttachment,
			IsPrimary: true,
		},
		{
			OwnerType: AssetOwnerTypeDataset,
			OwnerID:   uuid.New(),
			Role:      AssetReferenceRoleAttachment,
			IsPrimary: false,
		},
		{
			OwnerType: AssetOwnerTypeDataset,
			OwnerID:   uuid.New(),
			Role:      AssetReferenceRoleAttachment,
			IsPrimary: true,
		},
		{
			OwnerType: AssetOwnerTypeSample,
			OwnerID:   uuid.New(),
			Role:      AssetReferenceRolePrimary,
			IsPrimary: true,
		},
		{
			OwnerType: AssetOwnerTypeSample,
			OwnerID:   uuid.New(),
			Role:      AssetReferenceRoleAttachment,
			IsPrimary: false,
		},
	}

	for _, binding := range validCases {
		if err := binding.Validate(); err != nil {
			t.Fatalf("expected binding to be valid: %+v err=%v", binding, err)
		}
	}

	invalidCases := []struct {
		name string
		in   DurableOwnerBinding
		err  error
	}{
		{
			name: "unsupported owner type",
			in: DurableOwnerBinding{
				OwnerType: AssetOwnerType("runtime"),
				OwnerID:   uuid.New(),
				Role:      AssetReferenceRoleAttachment,
			},
			err: ErrUnsupportedAssetOwnerType,
		},
		{
			name: "missing owner id",
			in: DurableOwnerBinding{
				OwnerType: AssetOwnerTypeProject,
				Role:      AssetReferenceRoleAttachment,
			},
			err: ErrAssetOwnerIDRequired,
		},
		{
			name: "project primary role disallowed",
			in: DurableOwnerBinding{
				OwnerType: AssetOwnerTypeProject,
				OwnerID:   uuid.New(),
				Role:      AssetReferenceRolePrimary,
				IsPrimary: true,
			},
			err: ErrInvalidDurableOwnerBinding,
		},
		{
			name: "dataset primary role disallowed",
			in: DurableOwnerBinding{
				OwnerType: AssetOwnerTypeDataset,
				OwnerID:   uuid.New(),
				Role:      AssetReferenceRolePrimary,
				IsPrimary: true,
			},
			err: ErrInvalidDurableOwnerBinding,
		},
		{
			name: "sample primary must be primary flag",
			in: DurableOwnerBinding{
				OwnerType: AssetOwnerTypeSample,
				OwnerID:   uuid.New(),
				Role:      AssetReferenceRolePrimary,
				IsPrimary: false,
			},
			err: ErrInvalidDurableOwnerBinding,
		},
		{
			name: "sample attachment cannot be primary flag",
			in: DurableOwnerBinding{
				OwnerType: AssetOwnerTypeSample,
				OwnerID:   uuid.New(),
				Role:      AssetReferenceRoleAttachment,
				IsPrimary: true,
			},
			err: ErrInvalidDurableOwnerBinding,
		},
	}

	for _, tc := range invalidCases {
		err := tc.in.Validate()
		if !errors.Is(err, tc.err) {
			t.Fatalf("%s: expected %v got %v", tc.name, tc.err, err)
		}
	}
}
