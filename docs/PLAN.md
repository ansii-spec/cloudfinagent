# CloudFinAgent frontend plan

CloudFinAgent connects to a company's AWS account, finds wasted spend, suggests
changes, applies them with monitoring, and rolls them back if something breaks.

This plan covers the web frontend. It is built from `wireframes/` and `diagrams/`.
There is no backend yet, so the UI runs on mock data behind an API layer shaped
like the endpoints in `diagrams/suggestion-management-sequence.mmd`.

## Stack

| Concern | Choice |
| --- | --- |
| Build | Vite, React, TypeScript (strict) |
| UI components | shadcn/ui on Tailwind CSS |
| Routing | React Router |
| Server state | TanStack Query |
| Forms | React Hook Form with Zod |
| Charts | Recharts through the shadcn chart component |
| Tables | TanStack Table through the shadcn data table pattern |
| Tests | Vitest and Testing Library |

The app lives in `web/`, which leaves room for a sibling `backend/`.

## React Native concepts on the web

| React Native | Web equivalent here |
| --- | --- |
| `View`, `Text`, `Pressable` | `div`, semantic text elements, `button` or `Link` |
| `StyleSheet` | Tailwind classes and shadcn theme tokens |
| `FlatList` | Paginated data table |
| `Modal` | shadcn `Dialog` (apply confirmation) |
| Bottom sheet | shadcn `Sheet` (resource detail) and `Popover` (schedule, dismiss) |
| Native stack navigator | Nested React Router routes |
| Bottom tab navigator | `AppShell` sidebar with an outlet |
| `navigation.navigate` | `useNavigate` and `Link` |
| Route params | URL path params |
| Screen state for filters | URL search params, so views can be shared and survive reload |
| Auth stack vs app stack | Public routes vs a protected route wrapper |
| `AsyncStorage` | Backend-set httpOnly cookie for sessions, `localStorage` for UI preferences only |
| `Alert`, toast | Sonner toast and `AlertDialog` |
| `useFocusEffect` refetch | TanStack Query refetch on window focus |
| `Platform`, `Dimensions` | Responsive Tailwind breakpoints |

Web-only work with no RN counterpart: keyboard focus handling, semantic tables,
browser history, and CSV downloads.

## Routes

| Route | Wireframe |
| --- | --- |
| `/login` | `1-login` |
| `/register` | `2-register` |
| `/onboarding/connect` | `3a-onboarding-connect-aws` |
| `/onboarding/analysis` | `3b-onboarding-initial-analysis` |
| `/dashboard` | `4-cost-savings-dashboard` |
| `/suggestions` | `5-suggestions`, `5b-apply-confirmation-modal` |
| `/resources` | `6-resources` |
| `/resources/:id` | `6b-resource-detail-side-panel` |
| `/actions` | `7-actions` |
| `/settings` | `8-settings` |

## Milestones

Each checkbox is roughly one small commit.

### 1. Foundation
- [x] Scaffold Vite, React and TypeScript in `web/`
- [x] Add Tailwind and initialise shadcn/ui
- [ ] Add the theme tokens, based on the monochrome wireframes
- [ ] Add ESLint, Prettier and a Vitest smoke test
- [ ] Add CI for lint, typecheck, test and build

### 2. App skeleton
- [ ] Router with a placeholder page for each route
- [ ] `AppShell`: sidebar, suggestions count badge, AWS account footer
- [ ] Shared `PageHeader`, `StatCard`, `StatusBadge`, `SectionCard`
- [ ] Domain types: suggestion, action, resource, account
- [ ] Mock API layer and TanStack Query provider

### 3. Authentication
- [ ] Login form with validation
- [ ] Register form with validation
- [ ] Auth context and protected routes

### 4. Onboarding
- [ ] Stepper component
- [ ] Connect AWS form, switching between IAM role and access key
- [ ] Connection test results panel
- [ ] Analysis progress screen with polling

### 5. Dashboard
- [ ] KPI cards
- [ ] Savings trend chart with 30, 60 and 90 day ranges
- [ ] Service breakdown table
- [ ] Recent actions table
- [ ] Account filter and "Run analysis now"

### 6. Suggestions
- [ ] Data table with status badges and pagination
- [ ] Filters, search and sort stored in the URL
- [ ] Row selection and bulk action bar
- [ ] Apply confirmation dialog
- [ ] Schedule popover
- [ ] Dismiss popover with reason, and Restore

### 7. Resources
- [ ] Table with service chips, region filter and search
- [ ] Detail sheet routed at `/resources/:id`
- [ ] Usage metric charts
- [ ] Related recommendation and action history
- [ ] CSV export

### 8. Actions
- [ ] Table with status chips and filters
- [ ] Roll back, Cancel and Retry
- [ ] Expandable timeline row
- [ ] CSV export

### 9. Settings
- [ ] Section navigation and cloud accounts table
- [ ] Analysis preferences and confidence threshold
- [ ] Auto-remediation toggles and rollback sensitivity
- [ ] Notification preferences
- [ ] Account details and team members
- [ ] Save and discard handling

### 10. Polish
- [ ] Loading, empty and error states on every page
- [ ] Responsive layout pass, with a collapsible sidebar on small screens
- [ ] Accessibility pass for keyboard use and labels
- [ ] Tests for the apply, dismiss and rollback flows

## Status model

Taken from the activity and sequence diagrams.

- Suggestion: `open`, `scheduled`, `applied`, `dismissed`, `not_accurate`
- Action: `pending`, `scheduled`, `applied` (monitoring for 72 hours), `completed`,
  `failed`, `rolled_back`

## Mock API contract

| Method and path | Used by |
| --- | --- |
| `GET /suggestions?status=` | Suggestions |
| `POST /suggestions/{id}/apply` | Apply and schedule (optional `runAt`) |
| `POST /suggestions/{id}/dismiss` | Dismiss, with `{ reason }` |
| `POST /actions/{id}/rollback` | Actions |

The diagrams only define these four. Endpoints for auth, onboarding, resources
and settings will be proposed in `web/src/api` and need agreeing with the backend.

## Open questions

1. **Forgot password:** the login page links to it, but there is no wireframe.
2. **Restore endpoint:** the UI has Restore, but the diagrams define no API for it.
3. **Wireframe data mismatches:** `db-reporting` is Open in Suggestions but
   Scheduled in Resources, and its action is dated 10-08 on the Dashboard but
   10-12 in Actions. Mock data will use Scheduled and 10-12.
4. **AWS secrets:** access keys must go straight to the backend and never be
   stored in the browser. The IAM role option stays the recommended path.
