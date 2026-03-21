package apihttp

import (
	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	authorizationdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/domain"
	identityapp "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/app"
)

func mapAuthSession(session *identityapp.AuthSession) *openapi.AuthSessionResponse {
	return &openapi.AuthSessionResponse{
		AccessToken:        session.AccessToken,
		RefreshToken:       session.RefreshToken,
		ExpiresIn:          session.ExpiresIn,
		MustChangePassword: session.MustChangePassword,
		User: openapi.AuthSessionUser{
			PrincipalID: session.User.PrincipalID.String(),
			Email:       session.User.Email,
			FullName:    session.User.FullName,
		},
	}
}

func mapCurrentUser(currentUser *identityapp.CurrentUser) *openapi.CurrentUserResponse {
	return &openapi.CurrentUserResponse{
		User: openapi.AuthSessionUser{
			PrincipalID: currentUser.User.PrincipalID.String(),
			Email:       currentUser.User.Email,
			FullName:    currentUser.User.FullName,
		},
		SystemRoles:        append([]string(nil), currentUser.SystemRoles...),
		Permissions:        authorizationdomain.CanonicalPermissions(currentUser.Permissions),
		MustChangePassword: currentUser.MustChangePassword,
	}
}

func mapUser(item identityapp.UserAdminView) openapi.UserListItem {
	response := openapi.UserListItem{
		ID:                 item.ID,
		Email:              item.Email,
		IsActive:           item.IsActive,
		MustChangePassword: item.MustChangePassword,
		CreatedAt:          item.CreatedAt,
		UpdatedAt:          item.UpdatedAt,
		Roles:              make([]openapi.UserRoleInfo, 0, len(item.Roles)),
	}
	if item.FullName != "" {
		response.FullName.SetTo(item.FullName)
	}
	for _, role := range item.Roles {
		response.Roles = append(response.Roles, openapi.UserRoleInfo{
			ID:          role.ID,
			Name:        role.Name,
			DisplayName: role.DisplayName,
			Color:       role.Color,
			IsSupremo:   role.IsSupremo,
		})
	}
	return response
}
