package effects

import (
	"context"

	runtimerepo "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/repo"
)

type PullTransport struct{}

func NewPullTransport() *PullTransport {
	return &PullTransport{}
}

func (*PullTransport) Mode() string {
	return "pull"
}

func (*PullTransport) DispatchAssign(context.Context, runtimerepo.AgentCommand) error {
	return nil
}

func (*PullTransport) DispatchCancel(context.Context, runtimerepo.AgentCommand) error {
	return nil
}
