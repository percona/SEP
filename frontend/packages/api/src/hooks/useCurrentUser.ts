import { useQuery } from '@tanstack/react-query';
import type { ApiError } from '../errors';
import type { components } from '../generated/main';
import { mainApi, throwOnApiError } from '../typed-client';

/**
 * Sample typed hook demonstrating the full codegen → openapi-fetch → React Query
 * pattern. `data` is typed as `CasdoorUser` directly from the generated spec;
 * `error` is an `ApiError` (thanks to `throwOnApiError`).
 *
 * Reference for new hooks: copy this structure when wrapping typed endpoints.
 */
type CurrentUser = components['schemas']['CasdoorUser'];

export function useCurrentUser() {
  return useQuery<CurrentUser, ApiError>({
    queryKey: ['users', 'me'],
    queryFn: () => throwOnApiError(mainApi.GET('/api/users/me')),
  });
}
