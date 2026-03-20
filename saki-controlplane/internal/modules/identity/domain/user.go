package domain

import (
	"time"

	"github.com/google/uuid"
)

type UserState string

const (
	UserStateActive   UserState = "active"
	UserStateInvited  UserState = "invited"
	UserStateDisabled UserState = "disabled"
	UserStateDeleted  UserState = "deleted"
)

type User struct {
	PrincipalID   uuid.UUID
	Email         string
	Username      *string
	FullName      *string
	AvatarAssetID *uuid.UUID
	State         UserState
	CreatedAt     time.Time
	UpdatedAt     time.Time
}

type AdminUserRecord struct {
	User               User
	PrincipalStatus    PrincipalStatus
	MustChangePassword bool
}
