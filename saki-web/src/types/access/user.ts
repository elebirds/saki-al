export interface RoleInfoMinimal {
  id: string;
  name: string;
  displayName: string;
}

export interface User {
  id: string;
  email: string;
  fullName?: string;
  isActive: boolean;
  avatarUrl?: string;
  createdAt: string;
  updatedAt: string;
  lastLoginAt?: string;
  roles: RoleInfoMinimal[];
}