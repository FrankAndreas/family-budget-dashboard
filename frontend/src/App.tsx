import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { AuthProvider, useAuth } from './AuthContext';
import Dashboard from './pages/dashboard/Dashboard';
import ChildCosts from './pages/ChildCosts';
import NoAccess from './pages/NoAccess';
import './index.css';

// What the logged-in person sees: the app, or for a child without Jugendlohn only their own costs
const Home = () => {
  const { user, state } = useAuth();
  const { t } = useTranslation();

  if (state === 'no_access' || state === 'hub_down') return <NoAccess reason={state} />;
  // Not logged in yet: the browser is on its way to the family hub's login
  if (!user) return <div className="flex h-screen items-center justify-center">{t('common.loading')}</div>;
  if (user.role === 'CHILD' && !user.has_allowance) return <ChildCosts />;
  return <Dashboard />;
};

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Home />} />
          {/* The login is the family hub's now; old links to /login land here */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
