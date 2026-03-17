package internalrpc

import (
	"slices"
	"testing"

	_ "github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"
	"google.golang.org/protobuf/reflect/protoregistry"
	"google.golang.org/protobuf/types/dynamicpb"
)

func TestAgentIngressRegisterCodec(t *testing.T) {
	service := requireServiceDescriptor(t, "saki.runtime.v1.AgentIngress")
	assertMethodNames(t, service, "Register", "Heartbeat", "PushTaskEvent")

	method := requireMethodDescriptor(t, service, "Register")
	agentIDField := requireFieldDescriptor(t, method.Input(), "agent_id")
	versionField := requireFieldDescriptor(t, method.Input(), "version")
	capabilitiesField := requireFieldDescriptor(t, method.Input(), "capabilities")

	original := dynamicpb.NewMessage(method.Input())
	original.Set(agentIDField, protoreflect.ValueOfString("agent-a"))
	original.Set(versionField, protoreflect.ValueOfString("1.0.0"))

	capabilities := original.Mutable(capabilitiesField).List()
	capabilities.Append(protoreflect.ValueOfString("gpu"))
	capabilities.Append(protoreflect.ValueOfString("yolo"))

	wire, err := proto.Marshal(original)
	if err != nil {
		t.Fatalf("marshal register request: %v", err)
	}

	decoded := dynamicpb.NewMessage(method.Input())
	if err := proto.Unmarshal(wire, decoded); err != nil {
		t.Fatalf("unmarshal register request: %v", err)
	}

	if got := decoded.Get(agentIDField).String(); got != "agent-a" {
		t.Fatalf("unexpected decoded register request agent_id=%q", got)
	}
	if got := decoded.Get(versionField).String(); got != "1.0.0" {
		t.Fatalf("unexpected decoded register request version=%q", got)
	}
	if got := decoded.Get(capabilitiesField).List().Len(); got != 2 {
		t.Fatalf(
			"unexpected decoded register request capabilities=%d",
			got,
		)
	}
}

func TestAgentIngressTaskEventEnvelopeCodec(t *testing.T) {
	service := requireServiceDescriptor(t, "saki.runtime.v1.AgentIngress")
	method := requireMethodDescriptor(t, service, "PushTaskEvent")

	eventField := requireFieldDescriptor(t, method.Input(), "event")
	envelopeDescriptor := eventField.Message()
	agentIDField := requireFieldDescriptor(t, envelopeDescriptor, "agent_id")
	taskIDField := requireFieldDescriptor(t, envelopeDescriptor, "task_id")
	executionIDField := requireFieldDescriptor(t, envelopeDescriptor, "execution_id")
	phaseField := requireFieldDescriptor(t, envelopeDescriptor, "phase")
	logField := requireFieldDescriptor(t, envelopeDescriptor, "log")

	logMessage := dynamicpb.NewMessage(logField.Message())
	logMessage.Set(requireFieldDescriptor(t, logField.Message(), "level"), protoreflect.ValueOfString("INFO"))
	logMessage.Set(requireFieldDescriptor(t, logField.Message(), "message"), protoreflect.ValueOfString("task started"))

	envelope := dynamicpb.NewMessage(envelopeDescriptor)
	envelope.Set(agentIDField, protoreflect.ValueOfString("agent-a"))
	envelope.Set(taskIDField, protoreflect.ValueOfString("task-1"))
	envelope.Set(executionIDField, protoreflect.ValueOfString("exec-1"))
	envelope.Set(phaseField, protoreflect.ValueOfEnum(requireEnumValue(t, phaseField.Enum(), "TASK_EVENT_PHASE_RUNNING")))
	envelope.Set(logField, protoreflect.ValueOfMessage(logMessage))

	original := dynamicpb.NewMessage(method.Input())
	original.Set(eventField, protoreflect.ValueOfMessage(envelope))

	wire, err := proto.Marshal(original)
	if err != nil {
		t.Fatalf("marshal task event request: %v", err)
	}

	decoded := dynamicpb.NewMessage(method.Input())
	if err := proto.Unmarshal(wire, decoded); err != nil {
		t.Fatalf("unmarshal task event request: %v", err)
	}

	decodedEnvelope := decoded.Get(eventField).Message()
	if got := decodedEnvelope.Get(agentIDField).String(); got != "agent-a" {
		t.Fatalf("unexpected decoded task event agent_id=%q", got)
	}
	logPayload := decodedEnvelope.Get(logField).Message()
	if got := logPayload.Get(requireFieldDescriptor(t, logField.Message(), "message")).String(); got != "task started" {
		t.Fatalf(
			"unexpected decoded task event envelope log message=%q",
			got,
		)
	}
}

func TestAgentControlAssignTaskCodec(t *testing.T) {
	service := requireServiceDescriptor(t, "saki.runtime.v1.AgentControl")
	assertMethodNames(t, service, "AssignTask", "StopTask")

	method := requireMethodDescriptor(t, service, "AssignTask")
	taskIDField := requireFieldDescriptor(t, method.Input(), "task_id")
	executionIDField := requireFieldDescriptor(t, method.Input(), "execution_id")
	taskTypeField := requireFieldDescriptor(t, method.Input(), "task_type")
	payloadField := requireFieldDescriptor(t, method.Input(), "payload")

	original := dynamicpb.NewMessage(method.Input())
	original.Set(taskIDField, protoreflect.ValueOfString("task-1"))
	original.Set(executionIDField, protoreflect.ValueOfString("exec-1"))
	original.Set(taskTypeField, protoreflect.ValueOfString("demo"))
	original.Set(payloadField, protoreflect.ValueOfBytes([]byte("hello")))

	wire, err := proto.Marshal(original)
	if err != nil {
		t.Fatalf("marshal assign task request: %v", err)
	}

	decoded := dynamicpb.NewMessage(method.Input())
	if err := proto.Unmarshal(wire, decoded); err != nil {
		t.Fatalf("unmarshal assign task request: %v", err)
	}

	if got := decoded.Get(taskIDField).String(); got != "task-1" {
		t.Fatalf("unexpected decoded assign task request task_id=%q", got)
	}
	if got := string(decoded.Get(payloadField).Bytes()); got != "hello" {
		t.Fatalf("unexpected decoded assign task request payload=%q", got)
	}
}

func requireServiceDescriptor(t *testing.T, fullName protoreflect.FullName) protoreflect.ServiceDescriptor {
	t.Helper()

	descriptor, err := protoregistry.GlobalFiles.FindDescriptorByName(fullName)
	if err != nil {
		t.Fatalf("find service descriptor %q: %v", fullName, err)
	}

	service, ok := descriptor.(protoreflect.ServiceDescriptor)
	if !ok {
		t.Fatalf("descriptor %q is %T, want service descriptor", fullName, descriptor)
	}
	return service
}

func requireMethodDescriptor(
	t *testing.T,
	service protoreflect.ServiceDescriptor,
	name protoreflect.Name,
) protoreflect.MethodDescriptor {
	t.Helper()

	method := service.Methods().ByName(name)
	if method == nil {
		t.Fatalf("service %q missing method %q", service.FullName(), name)
	}
	return method
}

func requireFieldDescriptor(
	t *testing.T,
	message protoreflect.MessageDescriptor,
	name protoreflect.Name,
) protoreflect.FieldDescriptor {
	t.Helper()

	field := message.Fields().ByName(name)
	if field == nil {
		t.Fatalf("message %q missing field %q", message.FullName(), name)
	}
	return field
}

func requireEnumValue(
	t *testing.T,
	enum protoreflect.EnumDescriptor,
	name protoreflect.Name,
) protoreflect.EnumNumber {
	t.Helper()

	value := enum.Values().ByName(name)
	if value == nil {
		t.Fatalf("enum %q missing value %q", enum.FullName(), name)
	}
	return value.Number()
}

func assertMethodNames(
	t *testing.T,
	service protoreflect.ServiceDescriptor,
	want ...protoreflect.Name,
) {
	t.Helper()

	got := make([]protoreflect.Name, 0, service.Methods().Len())
	for i := 0; i < service.Methods().Len(); i++ {
		got = append(got, service.Methods().Get(i).Name())
	}
	if !slices.Equal(got, want) {
		t.Fatalf("unexpected methods for %q: got=%v want=%v", service.FullName(), got, want)
	}
}
