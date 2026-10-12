# Multi-User Budget Dashboard - Implementation Plan

## 1. Project Overview
A containerized, privacy-focused budget management application for families. 
- **Core Value**: Detailed financial tracking for parents with strict separation, aggregated views for family overview, and a gamified/private experience for children.
- **Tech Stack**: 
  - **Backend**: FastAPI (Python)
  - **Database**: SQLite (Embedded)
  - **Frontend**: React + TypeScript + Vite
  - **Deployment**: Docker Compose
  - **Styling**: Vanilla CSS (CSS Variables, Flex/Grid) with a focus on Glassmorphism and animations.

## 2. Architecture & Data Model

### Database Schema (SQLite)
We need a schema that supports strict data ownership and permission toggles.

- **Users**
  - `id`: UUID
  - `username`: String
  - `pin_hash`: String (bcrypt)
  - `role`: Enum (PARENT, CHILD)
  - `privacy_enabled`: Boolean (Only for children, default False)
  - `settings`: JSON (Theme prefs, etc.)

- **Accounts**
  - `id`: UUID
  - `user_id`: UUID (Foreign Key)
  - `name`: String (e.g., "Dad's Checking", "Timmy's Wallet")
  - `type`: Enum (CASH, BANK, SAVINGS)
  - `balance`: Decimal

- **Categories**
  - `id`: UUID
  - `name`: String
  - `type`: Enum (INCOME, EXPENSE)
  - `icon`: String
  - `is_global`: Boolean (Managed by parents)

- **Transactions**
  - `id`: UUID
  - `account_id`: UUID
  - `category_id`: UUID
  - `amount`: Decimal
  - `date`: DateTime
  - `description`: String

- **Budgets**
  - `id`: UUID
  - `user_id`: UUID
  - `category_id`: UUID
  - `limit`: Decimal
  - `period`: Enum (MONTHLY, YEARLY)

### Privacy Logic (Backend Middleware)
- **Parent Access**: Can access their own data + Child data (IF `child.privacy_enabled` is False). Cannot access other Parent's individual data.
- **Child Access**: Can only access their own data.
- **Aggregated View**: A dedicated endpoint that sums data for Parents only.

## 3. Frontend Design System ("Premium Fintech")
- **Theme**: Dark Mode default. Deep slate/navy backgrounds.
- **Aesthetics**: 
  - **Glassmorphism**: Translucent cards with subtle borders and blur effects for budget summaries.
  - **Typography**: 'Inter' or 'Outfit' for a clean, modern look.
  - **Motion**: Framer Motion for page transitions and graph animations.
- **Color Palette**:
  - Background: `#0f172a` (Slate 900)
  - Surface: `rgba(30, 41, 59, 0.7)` (Slate 800 with opacity)
  - Primary: `#38bdf8` (Sky 400 - detailed actions)
  - Success: `#34d399` (Emerald 400 - Income/Savings)
  - Danger: `#f87171` (Red 400 - Overspending)
  - Accent: `#818cf8` (Indigo 400 - Child dashboards)

## 4. Implementation Steps

### Phase 0: Design & Prototyping (✅ Completed)
1.  **UI Concepts**: Generated 3 distinct proposals (Obsidian, Aurora, Neon). **(Done)**
2.  **Selection**: Proceeding with **Proposal 2: Aurora Glass** for a premium, modern feel. **(Done)**

### Phase 1: Foundation (✅ Completed)
1.  **Scaffolding**: Set up `docker-compose.yml`, backend `Dockerfile`, frontend `Dockerfile`. **(Done)**
2.  **Database**: Initialize SQLite with SQLAlchemy. Models created (`users`, `accounts`, etc.). **(Done)**
3.  **Auth**: Implement functionality for User creation and PIN login. **(Done)**

### Phase 2: Core Features (✅ Completed)
4.  **Transaction Management**: CRUD for Accounts and Transactions. **(Done)**
5.  **Budgeting**: Logic for setting limits and tracking progress. **(Done)**
6.  **Dashboard**: The main UI with separate Parent/Child logic types. **(Done)**

### Phase 3: Analytics & Refinement (✅ Completed)
7.  **Charts**: Recharts integration for visualization. **(Done)**
8.  **Import/Export**: JSON and CSV handlers. **(Done)**
9.  **Polish**: Animations, responsive checks, robust error handling. **(Done)**
10. **Privacy Enforcement**: Backend middleware and API-level access control. **(Done)**

## 5. Directory Structure
```
/family-budget-dashboard
├── docker-compose.yml
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── models.py
│   │   ├── api.py
│   │   └── auth.py
│   ├── requirements.txt
│   └── Dockerfile
└── frontend/
    ├── src/
    │   ├── components/
    │   ├── pages/
    │   └── styles/ (CSS Modules or Global CSS)
    ├── package.json
    └── Dockerfile
```
