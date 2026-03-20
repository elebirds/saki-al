package app

import "errors"

var ErrRoleNotFound = errors.New("role not found")
var ErrRoleAlreadyExists = errors.New("role already exists")
var ErrRoleImmutable = errors.New("role is immutable")
var ErrInvalidRolePermission = errors.New("invalid role permission")
var ErrInvalidRoleScope = errors.New("invalid role scope")
var ErrInvalidRoleInput = errors.New("invalid role input")
var ErrLastSuperAdmin = errors.New("last super admin cannot be removed")
