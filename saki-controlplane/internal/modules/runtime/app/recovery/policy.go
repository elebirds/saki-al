package recovery

import "time"

const (
	defaultAssignAckTimeout      = 30 * time.Second
	defaultAgentHeartbeatTimeout = 30 * time.Second
)

// Policy 冻结 recovery 的最小判定窗口。
// 本阶段先把超时策略收敛在 runtime 内部，等部署面稳定后再暴露到配置层。
type Policy struct {
	AssignAckTimeout      time.Duration
	AgentHeartbeatTimeout time.Duration
}

func (p Policy) withDefaults() Policy {
	if p.AssignAckTimeout <= 0 {
		p.AssignAckTimeout = defaultAssignAckTimeout
	}
	if p.AgentHeartbeatTimeout <= 0 {
		p.AgentHeartbeatTimeout = defaultAgentHeartbeatTimeout
	}
	return p
}
