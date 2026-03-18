package sqlcdb

import (
	"reflect"
	"testing"
)

func TestGeneratedEnumTypes(t *testing.T) {
	t.Parallel()

	assertFieldTypeName(t, RuntimeTask{}, "Status", "RuntimeTaskStatus")
	assertFieldTypeName(t, RuntimeTask{}, "TaskKind", "RuntimeTaskKind")
	assertFieldTypeName(t, RuntimeExecutor{}, "Status", "RuntimeExecutorStatus")
	assertFieldTypeName(t, ImportTask{}, "Status", "ImportTaskStatus")
	assertFieldTypeName(t, ImportTaskEvent{}, "Phase", "ImportTaskEventPhase")
	assertFieldTypeName(t, ImportUploadSession{}, "Status", "ImportUploadSessionStatus")
	assertFieldTypeName(t, AccessPrincipal{}, "Status", "AccessPrincipalStatus")
	assertFieldTypeName(t, Asset{}, "Status", "AssetStatus")
	assertFieldTypeName(t, Asset{}, "Kind", "AssetKind")
	assertFieldTypeName(t, AssetUploadIntent{}, "State", "AssetUploadIntentState")

	assertFieldTypeName(t, CreateRuntimeTaskParams{}, "TaskKind", "RuntimeTaskKind")
	assertFieldTypeName(t, AdvanceRuntimeTaskByExecutionParams{}, "ToStatus", "RuntimeTaskStatus")
	assertSliceElemTypeName(t, AdvanceRuntimeTaskByExecutionParams{}, "FromStatuses", "RuntimeTaskStatus")
	assertFieldTypeName(t, UpdateRuntimeTaskParams{}, "Status", "RuntimeTaskStatus")
	assertFieldTypeName(t, AppendImportTaskEventParams{}, "Phase", "ImportTaskEventPhase")
}

func assertFieldTypeName(t *testing.T, target any, fieldName string, want string) {
	t.Helper()

	typ := reflect.TypeOf(target)
	field, ok := typ.FieldByName(fieldName)
	if !ok {
		t.Fatalf("%s missing field %s", typ.Name(), fieldName)
	}
	if got := field.Type.Name(); got != want {
		t.Fatalf("%s.%s type got %s want %s", typ.Name(), fieldName, got, want)
	}
}

func assertSliceElemTypeName(t *testing.T, target any, fieldName string, want string) {
	t.Helper()

	typ := reflect.TypeOf(target)
	field, ok := typ.FieldByName(fieldName)
	if !ok {
		t.Fatalf("%s missing field %s", typ.Name(), fieldName)
	}
	if field.Type.Kind() != reflect.Slice {
		t.Fatalf("%s.%s kind got %s want slice", typ.Name(), fieldName, field.Type.Kind())
	}
	if got := field.Type.Elem().Name(); got != want {
		t.Fatalf("%s.%s elem type got %s want %s", typ.Name(), fieldName, got, want)
	}
}
