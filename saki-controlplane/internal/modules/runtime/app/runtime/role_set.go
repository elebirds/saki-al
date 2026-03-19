package runtime

import "strings"

type RuntimeRole string

const (
	RuntimeRoleIngress   RuntimeRole = "ingress"
	RuntimeRoleScheduler RuntimeRole = "scheduler"
	RuntimeRoleDelivery  RuntimeRole = "delivery"
	RuntimeRoleRecovery  RuntimeRole = "recovery"
)

type RoleSet map[RuntimeRole]struct{}

func DefaultRoleSet() RoleSet {
	return NewRoleSet(
		string(RuntimeRoleIngress),
		string(RuntimeRoleScheduler),
		string(RuntimeRoleDelivery),
		string(RuntimeRoleRecovery),
	)
}

func NewRoleSet(values ...string) RoleSet {
	roles := make(RoleSet, len(values))
	for _, value := range values {
		role, ok := normalizeRuntimeRole(value)
		if !ok {
			continue
		}
		roles[role] = struct{}{}
	}
	if len(roles) == 0 {
		return DefaultRoleSetWithoutFallback()
	}
	return roles
}

func DefaultRoleSetWithoutFallback() RoleSet {
	return RoleSet{
		RuntimeRoleIngress:   {},
		RuntimeRoleScheduler: {},
		RuntimeRoleDelivery:  {},
		RuntimeRoleRecovery:  {},
	}
}

func (r RoleSet) Has(role RuntimeRole) bool {
	if len(r) == 0 {
		return false
	}
	_, ok := r[role]
	return ok
}

func normalizeRuntimeRole(value string) (RuntimeRole, bool) {
	switch RuntimeRole(strings.TrimSpace(value)) {
	case RuntimeRoleIngress:
		return RuntimeRoleIngress, true
	case RuntimeRoleScheduler:
		return RuntimeRoleScheduler, true
	case RuntimeRoleDelivery:
		return RuntimeRoleDelivery, true
	case RuntimeRoleRecovery:
		return RuntimeRoleRecovery, true
	default:
		return "", false
	}
}
