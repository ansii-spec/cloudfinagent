# CloudFinAgent

Final year project: an agent that finds wasted AWS spend, suggests changes, applies
them with monitoring, and rolls them back when something breaks.

This repository currently holds the web frontend in `web/`. It runs on mock data;
there is no backend yet.

## Requirements

- [Node.js](https://nodejs.org/) 22 or newer (includes npm)

## Run the project

```bash
cd web
npm install
npm run dev
```

Then open <http://localhost:5173> in your browser. The app starts on the login page;
any valid-looking email and any password will log you in while the backend is missing.

## Scripts

Run these inside `web/`:

| Command | What it does |
| --- | --- |
| `npm run dev` | Start the development server with live reload |
| `npm run build` | Build a production bundle into `web/dist/` |
| `npm run preview` | Serve the production build locally |
| `npm run lint` | Check the code with Oxlint |

## Tech stack

- React 19 with JavaScript, built with Vite
- Tailwind CSS and shadcn/ui components
- React Router for pages, Recharts for charts

## Project structure

```text
web/
  src/
    pages/              One file per screen (Login, Register, Dashboard, ...)
    components/layout/  App shell (top bar, sidebar) and the sign-in layout
    components/common/  Shared page header, cards, tables, status badges, form fields
    components/ui/      shadcn/ui components
    mock/               Sample data used until the backend exists
    router.js           Route definitions
    index.css           Theme colours and base styles
```

## Screens

| Route | Status |
| --- | --- |
| `/login`, `/register` | Done |
| `/dashboard` | Done |
| `/onboarding/*`, `/suggestions`, `/resources`, `/actions`, `/settings` | Placeholder |
