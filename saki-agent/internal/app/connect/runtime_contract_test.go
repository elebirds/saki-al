package connect_test

import (
	"testing"

	_ "github.com/elebirds/saki/saki-agent/internal/gen/runtime/v1"
	"github.com/elebirds/saki/saki-agent/internal/gen/runtime/v1/runtimev1connect"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"
	"google.golang.org/protobuf/reflect/protoregistry"
	"google.golang.org/protobuf/types/dynamicpb"
)

func TestRuntimeProtoContractSmoke(t *testing.T) {
	t.Helper()

	var _ = runtimev1connect.NewAgentIngressClient
	var _ = runtimev1connect.NewAgentControlHandler
	var _ = runtimev1connect.NewAgentDeliveryClient
}

func TestAgentIngressRegisterContract(t *testing.T) {
	service := requireServiceDescriptor(t, "saki.runtime.v1.AgentIngress")
	method := requireMethodDescriptor(t, service, "Register")

	agentIDField := requireFieldDescriptor(t, method.Input(), "agent_id")
	transportModeField := requireFieldDescriptor(t, method.Input(), "transport_mode")
	controlBaseURLField := requireFieldDescriptor(t, method.Input(), "control_base_url")
	maxConcurrencyField := requireFieldDescriptor(t, method.Input(), "max_concurrency")

	original := dynamicpb.NewMessage(method.Input())
	original.Set(agentIDField, protoreflect.ValueOfString("agent-a"))
	original.Set(transportModeField, protoreflect.ValueOfString("pull"))
	original.Set(controlBaseURLField, protoreflect.ValueOfString("http://127.0.0.1:18081"))
	original.Set(maxConcurrencyField, protoreflect.ValueOfInt32(2))

	wire, err := proto.Marshal(original)
	if err != nil {
		t.Fatalf("marshal register request: %v", err)
	}

	decoded := dynamicpb.NewMessage(method.Input())
	if err := proto.Unmarshal(wire, decoded); err != nil {
		t.Fatalf("unmarshal register request: %v", err)
	}
	if got := decoded.Get(maxConcurrencyField).Int(); got != 2 {
		t.Fatalf("unexpected decoded register request max_concurrency=%d", got)
	}
}

func TestAgentIngressHeartbeatContract(t *testing.T) {
	service := requireServiceDescriptor(t, "saki.runtime.v1.AgentIngress")
	method := requireMethodDescriptor(t, service, "Heartbeat")

	maxConcurrencyField := requireFieldDescriptor(t, method.Input(), "max_concurrency")
	original := dynamicpb.NewMessage(method.Input())
	original.Set(maxConcurrencyField, protoreflect.ValueOfInt32(3))

	wire, err := proto.Marshal(original)
	if err != nil {
		t.Fatalf("marshal heartbeat request: %v", err)
	}

	decoded := dynamicpb.NewMessage(method.Input())
	if err := proto.Unmarshal(wire, decoded); err != nil {
		t.Fatalf("unmarshal heartbeat request: %v", err)
	}
	if got := decoded.Get(maxConcurrencyField).Int(); got != 3 {
		t.Fatalf("unexpected decoded heartbeat request max_concurrency=%d", got)
	}
}

func TestAgentDeliveryContract(t *testing.T) {
	service := requireServiceDescriptor(t, "saki.runtime.v1.AgentDelivery")
	pullMethod := requireMethodDescriptor(t, service, "PullCommands")

	agentIDField := requireFieldDescriptor(t, pullMethod.Input(), "agent_id")
	maxItemsField := requireFieldDescriptor(t, pullMethod.Input(), "max_items")
	waitTimeoutField := requireFieldDescriptor(t, pullMethod.Input(), "wait_timeout_ms")

	original := dynamicpb.NewMessage(pullMethod.Input())
	original.Set(agentIDField, protoreflect.ValueOfString("agent-pull-1"))
	original.Set(maxItemsField, protoreflect.ValueOfInt32(8))
	original.Set(waitTimeoutField, protoreflect.ValueOfInt64(25000))

	wire, err := proto.Marshal(original)
	if err != nil {
		t.Fatalf("marshal pull request: %v", err)
	}

	decoded := dynamicpb.NewMessage(pullMethod.Input())
	if err := proto.Unmarshal(wire, decoded); err != nil {
		t.Fatalf("unmarshal pull request: %v", err)
	}
	if got := decoded.Get(maxItemsField).Int(); got != 8 {
		t.Fatalf("unexpected decoded pull request max_items=%d", got)
	}

	ackMethod := requireMethodDescriptor(t, service, "AckCommand")
	stateField := requireFieldDescriptor(t, ackMethod.Input(), "state")
	ackOriginal := dynamicpb.NewMessage(ackMethod.Input())
	ackOriginal.Set(stateField, protoreflect.ValueOfString("received"))

	ackWire, err := proto.Marshal(ackOriginal)
	if err != nil {
		t.Fatalf("marshal ack request: %v", err)
	}

	ackDecoded := dynamicpb.NewMessage(ackMethod.Input())
	if err := proto.Unmarshal(ackWire, ackDecoded); err != nil {
		t.Fatalf("unmarshal ack request: %v", err)
	}
	if got := ackDecoded.Get(stateField).String(); got != "received" {
		t.Fatalf("unexpected decoded ack request state=%q", got)
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

func requireMethodDescriptor(t *testing.T, service protoreflect.ServiceDescriptor, name protoreflect.Name) protoreflect.MethodDescriptor {
	t.Helper()

	method := service.Methods().ByName(name)
	if method == nil {
		t.Fatalf("service %q missing method %q", service.FullName(), name)
	}
	return method
}

func requireFieldDescriptor(t *testing.T, message protoreflect.MessageDescriptor, name protoreflect.Name) protoreflect.FieldDescriptor {
	t.Helper()

	field := message.Fields().ByName(name)
	if field == nil {
		t.Fatalf("message %q missing field %q", message.FullName(), name)
	}
	return field
}
