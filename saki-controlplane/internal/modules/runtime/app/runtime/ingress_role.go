package runtime

func ingressRoleHandlers(roles RoleSet, mounts []rpcHandlerMount) []rpcHandlerMount {
	if !roles.Has(RuntimeRoleIngress) {
		return nil
	}

	handlers := make([]rpcHandlerMount, 0, len(mounts))
	for _, mount := range mounts {
		if mount.path == "" || mount.handler == nil {
			continue
		}
		handlers = append(handlers, mount)
	}
	return handlers
}
