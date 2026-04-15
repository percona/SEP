# 7. Codebase Walkthrough for Vue Developers

## What this commit introduced

The last commit (`7a242084`, `feat(sep-react): schema-driven plugin architecture POC`) turns `sep-react` into a small monorepo and proves the main migration idea:

- the shell owns app boot, routing, auth, layout, and global providers
- `@sep/api` owns HTTP, auth calls, typed contracts, and React Query hooks
- `@sep/framework` owns the reusable UI engine
- each plugin should ideally provide only schema data plus sample data, not custom React pages

The `checksums` plugin is the proof-of-concept. It contains almost no UI logic. The framework renders its list page, create page, and detail page from schema and task data.

## The mental model for a Vue developer

If you mainly work in Vue, this React codebase becomes easier to read if you map concepts like this:

| React code here                                          | Closest Vue idea                                       |
| -------------------------------------------------------- | ------------------------------------------------------ |
| `main.tsx`                                               | `main.ts` boot file                                    |
| `RouterProvider` + `createBrowserRouter`                 | Vue Router setup                                       |
| Context providers (`AuthProvider`, `NavigationProvider`) | `provide/inject`, app plugins, or a small global store |
| React Query hooks                                        | Vue Query / composables for server state               |
| `react-hook-form` control object                         | form composable state passed into field components     |
| `useWatch`                                               | `watch()` on a form field                              |
| `useMemo`                                                | `computed()`                                           |
| `useEffect`                                              | `watchEffect()` / `onMounted()` side effects           |
| Lazy route imports                                       | async route components                                 |

Important design choice: this app does **not** use a big client-side store for server data. It treats backend data as server state and lets React Query cache and invalidate it. That is why most data access lives in hooks instead of a global state module.

## Monorepo layout

`sep-react` is a pnpm workspace with five packages:

### `packages/shell`

The application shell. It owns:

- app bootstrap
- theme setup
- React Query provider
- router
- auth and navigation contexts
- layouts like header and sidebar

This is roughly the Vue app shell plus router plus global app plugins.

### `packages/api`

The typed boundary to the backend. It owns:

- the Axios client
- auth calls
- shared API types
- `PluginSchema` types
- React Query hooks for schema and task CRUD

This is the equivalent of a shared `api/` layer plus typed composables.

### `packages/framework`

The reusable UI engine. It owns:

- `SchemaDrivenPlugin`
- `SchemaFormRenderer`
- `SchemaListView`
- inventory-aware selectors
- stubbed shared capability components such as logs, chaining, and scheduling

This is the core architectural bet of the PR. It centralizes shared UI so plugins do not duplicate list pages, forms, and detail screens.

### `packages/checksums`

The first real plugin consumer. It only provides:

- `schema.ts`
- `mock-data.ts`
- `ChecksumsPlugin.tsx`

That is the proof that a plugin can be mostly configuration.

### `packages/shared`

Now intentionally tiny. It only exports constants like route paths and app names.

This matters because the commit moves API concerns out of `shared` and into `api`, which makes boundaries cleaner.

## Boot sequence

The runtime starts in `packages/shell/src/main.tsx`.

### 1. `main.tsx`

It mounts the app and installs two top-level providers:

- `QueryClientProvider`
- `ThemeProvider`

Why:

- `QueryClientProvider` gives every component access to React Query's cache, fetch lifecycle, loading states, and invalidation
- `ThemeProvider` wraps Percona's shared UI theme and color-mode support

For a Vue dev, think of this like mounting the app with Vue Query and a UI framework plugin at the root.

### 2. `App.tsx`

`App.tsx` is intentionally thin. It just renders:

```tsx
<RouterProvider router={router} />
```

So the router, not `App`, becomes the real page composition entry.

### 3. `router.tsx`

The router defines three main layers:

1. `RootLayout`
2. `/login`
3. authenticated routes under `/`

`RootLayout` wraps everything in `Providers`, then exposes an `<Outlet />`.

That means the provider tree is tied to the route tree, not manually nested in `main.tsx`.

This is a common React Router pattern. In Vue terms, it is similar to making the root route component own global wrappers around all child routes.

## Providers and why they exist

### `ThemeProvider`

Location: `packages/shell/src/contexts/theme.tsx`

This wraps Percona's `ThemeContextProvider` using SEP-specific theme options from `theme.ts`.

What it provides:

- light/dark mode
- SEP brand colors
- typography overrides
- localStorage persistence for color mode

Why it is done this way:

- the app wants one source of truth for design tokens
- Percona already has a React component library built on MUI
- the shell should define branding once and let all packages inherit it

### `QueryClientProvider`

Location: `packages/shell/src/main.tsx`

This is the app-wide server-state cache. Default behavior here is intentionally conservative:

- `refetchOnWindowFocus: false`
- `retry: 1`

Why:

- schemas and task data come from the backend
- multiple pages may need the same data
- React Query prevents each page from reimplementing loading, caching, and invalidation

For a Vue dev: this fills the role that many teams accidentally push into Pinia. Here, it stays in a query cache instead.

### `SnackbarProvider`

Location: `packages/shell/src/Providers.tsx`

This provides toast notifications through `notistack`, styled with `@percona/percona-ui`.

Why:

- mutation results like "task created" should be triggered from anywhere
- toasts are a cross-cutting concern, so they belong in a global provider

### `AuthProvider`

Location: `packages/shell/src/contexts/auth.tsx`

This is one of the key providers.

It owns:

- `user`
- `token`
- auth flags such as `isAuthenticated`, `isAdmin`, `loading`, `ready`
- actions: `login`, `logout`, `mockLogin`
- token persistence in localStorage
- token refresh scheduling
- initial session bootstrap

Why React Context is used here:

- auth is global, but still fairly small
- it is not server-cache data in the React Query sense
- passing auth props through the tree would be noisy

This is conceptually close to a tiny auth store or injected auth service in Vue.

### Auth flow

On mount, `AuthProvider`:

1. reads `sep_token` from localStorage
2. if no token exists, marks itself `ready`
3. if a real token exists, calls `fetchCurrentUser()`
4. if that succeeds, stores the user and starts refresh timing
5. if that fails, clears tokens silently

During login:

1. `LoginPage` calls `auth.login(username, password)`
2. `postLogin()` sends `POST /api/oauth/token`
3. the provider stores access and refresh tokens
4. it fetches `/api/users/me`
5. it schedules token refresh before expiry

There is also a mock path for development:

- if backend auth is unavailable, the login page enables mock mode
- `mockLogin()` creates a fake user and stores a fake token

This is why the POC works even without a complete backend.

### `NavigationProvider`

Location: `packages/shell/src/contexts/navigation.tsx`

This holds:

- sidebar open/closed state
- the sidebar item tree

Right now the navigation config is hard-coded. The file even includes a TODO saying it should eventually come from `/api/plugins`.

Why it exists:

- header and sidebar both need access to navigation state
- the shell owns navigation, not individual plugins

For Vue, think of it as shared layout state provided near the top of the route tree.

## Route and layout flow

Once providers exist, the route flow is:

1. `RootLayout` mounts shared providers
2. `/login` renders the login page directly
3. `/` is wrapped in `AuthGuard`
4. `AuthGuard` waits for auth bootstrap
5. unauthenticated users are redirected to `/login?redirect=...`
6. authenticated users render `MainLayout`
7. `MainLayout` renders header, sidebar, and the current page outlet

`MainLayout` is just a shell frame. It does not own plugin data.

That separation is intentional:

- shell concerns stay in `shell`
- plugin concerns stay in plugin/framework packages

## API layer

`@sep/api` is where the app stops being "React UI" and starts being "frontend client for SEP APIs".

### `client.ts`

This creates the shared Axios instance:

- base URL is `/api`
- request/response key conversion is handled by `axios-case-converter`
- each request attaches `Authorization: Bearer <token>` from localStorage

The response interceptor handles auth failures globally:

- on `401` or `303`, it clears stored tokens
- if the user is not already on `/login`, it redirects to login with a return URL

Why this is useful:

- auth behavior stays centralized
- every hook and API helper does not need its own auth error code

### `auth.ts`

This file defines the auth-specific API calls:

- `postLogin()`
- `postRefresh()`
- `fetchCurrentUser()`

The `postLogin()` detail matters: it sends `application/x-www-form-urlencoded`, because the backend expects OAuth2 password-form semantics.

### `types/plugin-schema.ts`

This is the central domain contract for schema-driven plugins.

The important idea is the discriminated union on `field.type`.

Example field families:

- scalar inputs: `string`, `integer`, `float`, `bool`, `choice`, `textarea`, `datetime`, `file`, `yaml`
- inventory-aware inputs: `service`, `schema`, `table`

This is why the framework can render a form from JSON-like schema data. The renderer switches on `field.type` and chooses the right UI component.

For a Vue dev, imagine a big dynamic-field component that receives a schema object and uses `v-if` or `<component :is="...">` to render the correct input. The same idea is happening here, just with React's `switch` and JSX.

### React Query hooks

The key hooks are:

- `usePluginSchema(pluginName, mockSchema?)`
- `usePluginTasks(pluginName, mockTasks?)`
- `usePluginTask(pluginName, taskId, mockTasks?)`
- `useCreatePluginTask(pluginName)`

Why hooks instead of direct API calls in pages:

- pages stay declarative
- loading and error states stay close to the data consumer
- caching and invalidation stay centralized

Example:

- `usePluginSchema('checksums', checksumsSchema)` returns mock schema immediately in the POC
- later, the same hook can fetch the real backend schema without changing page components

That is a strong migration property: the UI shape can stay stable while the backend catches up.

## Framework layer

This is the heart of the POC.

### `SchemaDrivenPlugin`

Location: `packages/framework/src/components/SchemaDrivenPlugin/SchemaDrivenPlugin.tsx`

This component is the generic plugin container.

It:

1. fetches the plugin schema
2. waits for loading or error resolution
3. creates nested plugin-local routes
4. renders:
   - list page at index
   - create page at `new`
   - detail page at `:id`

This is the most important abstraction in the repo.

Why it exists:

- every simple plugin has the same page shape
- list/create/detail should not be rewritten package by package
- plugins should provide metadata, not custom page code

For Vue, it is like a reusable route module that takes a schema prop and internally defines list/create/detail pages with child routes.

### `PluginListPage`

This page:

- fetches task rows with `usePluginTasks`
- renders a heading from `schema.displayName`
- renders the generic `SchemaListView`
- navigates to `new` or `:id`

The plugin-specific part is just the schema and task data. The page component itself is generic.

### `PluginCreatePage`

This page:

- uses `useCreatePluginTask`
- renders `SchemaFormRenderer`
- shows success or error toasts
- invalidates the task list through the mutation hook

The mutation itself is generic. Only `pluginName` changes.

### `PluginDetailPage`

This page:

- reads `id` from the route
- fetches one task with `usePluginTask`
- renders visible fields from `schema.listView.columns`
- then renders extra task properties not already shown in the list schema

This is a useful POC move: it avoids designing a separate detail-view schema before proving the core architecture.

### `SchemaFormRenderer`

This component takes `sections` and `onSubmit`.

Its responsibilities:

- derive initial form defaults from schema plus optional `defaultValues`
- create one `react-hook-form` instance
- render each section title and description
- render each field through `FieldRenderer`
- submit the final data object

Why `react-hook-form` is used:

- Percona UI field components already integrate with it
- it keeps form state local to the form
- it avoids each input managing its own state manually

For a Vue dev, this is similar to having one form composable that registers child inputs against a shared controller.

### `FieldRenderer`

This is where the schema becomes concrete UI.

It switches on `field.type` and chooses:

- `TextInput`
- `SelectInput`
- `SwitchInput`
- `ServiceSelector`
- `SchemaSelector`
- `TableSelector`

It also converts schema validation into input rules.

This is the core "renderer" pattern. If a new field type is added to `PluginSchema`, this is one of the main files that must learn how to display it.

### Inventory-aware selectors

The selectors are:

- `ServiceSelector`
- `SchemaSelector`
- `TableSelector`

These matter because plugin forms often depend on inventory state.

### `ServiceSelector`

Fetches services and optionally filters by service type.

In the POC it uses mock data and React Query.

### `SchemaSelector`

Watches another field with `useWatch`, typically the selected service ID.

When that upstream value exists, it queries schemas for that service and enables the dropdown.

This is a classic dependent-select pattern.

For Vue, it is close to:

- watching `serviceId`
- fetching schemas when it changes
- disabling the child select until the parent is chosen

### `TableSelector`

Same pattern as `SchemaSelector`, but depends on the selected schema.

The important architectural point is that these selectors are shared framework components, not plugin code.

That keeps plugin schemas declarative:

- a plugin says "this field is a `schema` field and depends on `serviceId`"
- the framework knows how to behave

### `SchemaListView`

This renders list pages from `schema.listView.columns`.

It maps each schema column to a `material-react-table` column and formats values according to `format`:

- `chip`
- `status`
- `date`
- `relative`
- `code`
- plain text

This makes plugin lists configurable from schema as well, not just forms.

### Shared capability components

The framework exports:

- `TaskLogViewer`
- `TaskHistoryTable`
- `ChainBuilder`
- `AlertOnFailField`
- `ScheduledTasksPanel`
- hooks like `useTaskLogs`, `useExecutionEvents`, `useTaskHistory`

These are important in the architecture docs because they represent shared cross-plugin concerns.

However, in this commit they are mostly stubs or standalone building blocks:

- they exist
- they have mock data or placeholder UIs
- but `SchemaDrivenPlugin` does **not** yet wire them into the generated pages

That is an important distinction between the PR description and the actual code state:

- the shared capability building blocks are present
- the end-to-end integration of capabilities into schema-driven pages is still future work

## The checksums plugin, piece by piece

This is the best file set to read if you want to understand the architectural style.

### `schema.ts`

This file is the plugin.

More precisely, it is the plugin-specific configuration that describes:

- plugin identity
- human-readable labels
- form sections
- form fields
- capabilities
- list columns and default sorting

What it does **not** describe:

- how to render text fields
- how to manage form state
- how to make list tables sortable
- how to navigate between list/create/detail

That is the whole point of the architecture.

### `mock-data.ts`

This provides sample task rows so the plugin can be demonstrated before the backend is finished.

This is useful for:

- UI work without backend dependency
- proving the list and detail pages
- validating the schema structure quickly

### `ChecksumsPlugin.tsx`

This file is intentionally tiny:

```tsx
<SchemaDrivenPlugin
  pluginName="checksums"
  mockSchema={checksumsSchema}
  mockTasks={[...mockChecksumTasks]}
/>
```

That is the whole proof-of-concept.

If you come from Vue, the equivalent would be a plugin route component that imports a schema object and passes it to a shared renderer component. The page itself contains almost no view logic.

## End-to-end data flow

Here is the practical runtime flow when a user opens the checksums plugin.

### A. App load and auth

1. `main.tsx` mounts React Query and theme
2. `RouterProvider` starts the route tree
3. `RootLayout` mounts snackbar, auth, and navigation providers
4. `AuthProvider` checks localStorage and optionally fetches the current user
5. `AuthGuard` either waits, redirects to login, or allows access

### B. Route resolution

1. user navigates to `/schema-change/checksums`
2. the router lazy-loads `@sep/checksums`
3. `ChecksumsPlugin` renders `SchemaDrivenPlugin`

### C. Schema fetch

1. `SchemaDrivenPlugin` calls `usePluginSchema('checksums', checksumsSchema)`
2. React Query resolves the query
3. because mock schema is passed, the POC can render immediately
4. once real backend schema exists, the same hook can fetch `/api/plugins/checksums/schema`

### D. List page

1. the index route renders `PluginListPage`
2. `PluginListPage` calls `usePluginTasks('checksums', mockTasks)`
3. data flows into `SchemaListView`
4. each schema column becomes a table column
5. clicking a row navigates to `:id`

### E. Create page

1. clicking "New Checksums" navigates to `new`
2. `PluginCreatePage` renders `SchemaFormRenderer`
3. `SchemaFormRenderer` builds form defaults from schema
4. `FieldRenderer` renders one input per field type
5. selectors may run dependent queries based on watched field values
6. submit calls `useCreatePluginTask('checksums')`
7. on success, the task list query is invalidated and a toast is shown

### F. Detail page

1. navigating to `/schema-change/checksums/:id` renders `PluginDetailPage`
2. `usePluginTask('checksums', id, mockTasks)` fetches the row
3. fields from `listView.columns` are shown first
4. extra properties are then rendered automatically

## Why it is built this way

This architecture is optimized for SEP's migration problem, not for React purity.

### 1. It minimizes per-plugin frontend code

SEP has many plugins with similar shapes:

- pick a target
- fill a form
- launch a task
- inspect status/history/logs

If each plugin owns its own React pages, the migration will duplicate the same work repeatedly. The schema-driven approach removes most of that duplication.

### 2. It keeps the backend as the source of truth

The architecture docs are explicit: the backend should serve plugin schema JSON and plugin task data. The frontend should be a renderer of those contracts.

That is good for SEP because:

- plugins already live conceptually on the backend
- validation rules can stay near domain logic
- the same API can serve future non-UI consumers

### 3. It cleanly separates concerns

- `shell` is application chrome and access control
- `api` is transport and contracts
- `framework` is reusable UI behavior
- plugins are configuration and domain specifics

This separation is especially helpful in a monorepo because package boundaries communicate intent.

### 4. It supports the migration strategy

The docs describe a strangler-fig migration from Jinja2 to React.

This structure helps because:

- shell and framework can be built once
- each plugin can migrate independently
- mock schema and mock tasks let frontend work continue before all APIs exist

### 5. It matches Percona's React ecosystem

The code leans on:

- MUI
- `@percona/percona-ui`
- React Query
- `react-hook-form`

That is why the app looks more provider-heavy than a typical Vue app. Those libraries are React-first, and the architecture is intentionally aligned with the existing Percona frontend stack.

## Current POC limitations and notable gaps

For understanding the codebase correctly, it is important to separate what is implemented now from what the docs describe as the target state.

### Implemented now

- monorepo structure
- shell, providers, router, and auth flow
- typed schema contract
- generic schema-driven list/create/detail pages
- checksums plugin as a real schema-driven example
- mock-mode fallback for unfinished backend pieces

### Not fully implemented yet

- real plugin schema fetch is still mocked when `mockSchema` is supplied
- real task create/list/detail calls are still mocked in the generic hooks
- inventory selectors still use mock inventory data
- capability components exist, but generated plugin pages do not yet mount them
- task log/history/event flows are placeholder hooks, not real backend integrations
- navigation is still hard-coded, not plugin-discovered

So the commit is best understood as a strong architecture POC, not a finished plugin platform.

## One subtle but important implementation detail

`packages/shell/vite.config.ts` includes a patch plugin for `@percona/percona-ui`.

Why:

- `percona-ui` tries to read `react-hook-form` context even when a field already receives an explicit `control` prop
- in this repo, fields are rendered by a schema renderer and rely on explicit `control`
- without the patch, some pre-bundled code crashes if form context is null

This is not product behavior. It is a compatibility patch needed to make the current dependency combination work in Vite.

## How a future schema-driven plugin is meant to be added

Based on this commit, the intended plugin authoring flow is:

1. define `schema.ts`
2. define `mock-data.ts` for local development
3. export a thin wrapper around `SchemaDrivenPlugin`
4. register one route in the shell

That is exactly the developer-experience goal described in the PR.

## Bottom line

This POC is building a React shell around a backend-defined plugin model.

The most important thing to understand is this:

- the plugin should describe **what** it needs
- the framework should decide **how** to render it

That is why so much code sits in providers, typed hooks, and generic renderers. The goal is not to make each plugin a handcrafted React app. The goal is to make most plugins look like configuration plus API contracts, with the framework doing the repetitive UI work once.
