package app

import "errors"

var ErrRoleNotFound = errors.New("role not found")
var ErrRoleAlreadyExists = errors.New("role already exists")
var ErrRoleImmutable = errors.New("role is immutable")
var ErrInvalidRolePermission = errors.New("invalid role permission")
var ErrInvalidRoleScope = errors.New("invalid role scope")
var ErrInvalidRoleInput = errors.New("invalid role input")
var ErrLastSuperAdmin = errors.New("last super admin cannot be removed")
var ErrInvalidResourceInput = errors.New("invalid resource input")
var ErrInvalidResourceType = errors.New("invalid resource type")
var ErrResourceNotFound = errors.New("resource not found")
var ErrResourceRoleNotAssignable = errors.New("resource role is not assignable")
var ErrResourceMembershipNotFound = errors.New("resource membership not found")
var ErrResourceOwnerImmutable = errors.New("resource owner membership is immutable")
