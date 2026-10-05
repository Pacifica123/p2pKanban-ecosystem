import { apiRequest, clearAccessToken } from '@/shared/api/client';
import type {
  AuthSuccessResponse,
  NodeLinkImportRequest,
  SessionResponse,
  SignInRequest,
  SignOutResponse,
  SignUpRequest,
} from '@/shared/types/api';

export async function signIn(input: SignInRequest) {
  return apiRequest<AuthSuccessResponse>('/auth/sign-in', {
    method: 'POST',
    body: JSON.stringify(input),
  }, { skipAuthRefresh: true });
}

export async function signUp(input: SignUpRequest) {
  return apiRequest<AuthSuccessResponse>('/auth/sign-up', {
    method: 'POST',
    body: JSON.stringify(input),
  }, { skipAuthRefresh: true });
}

export async function importAccountFromNode(input: NodeLinkImportRequest) {
  return apiRequest<AuthSuccessResponse>('/auth/node-link/import', {
    method: 'POST',
    body: JSON.stringify(input),
  }, { skipAuthRefresh: true });
}

export async function refreshSession() {
  const response = await apiRequest<AuthSuccessResponse>('/auth/refresh', {
    method: 'POST',
  }, { skipAuthRefresh: true });
  return response;
}

export async function getSession() {
  return apiRequest<SessionResponse>('/auth/session');
}

export async function signOut() {
  const response = await apiRequest<SignOutResponse>('/auth/sign-out', {
    method: 'POST',
  });
  clearAccessToken();
  return response;
}

export async function signOutAll() {
  const response = await apiRequest<SignOutResponse>('/auth/sign-out-all', {
    method: 'POST',
  });
  clearAccessToken();
  return response;
}
