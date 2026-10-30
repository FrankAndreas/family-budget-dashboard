import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react';
import api, { errorCode, goToHubLogout } from './api';
import { applyLanguage, type Language } from './i18n';

interface User {
    id: string;
    username: string;
    role: 'PARENT' | 'CHILD';
    privacy_enabled?: boolean;
    has_allowance: boolean;
    language: Language;
}

// Where the login stands: still asking, logged in, logged in at the hub without access here, or the hub can't be reached
export type AuthState = 'loading' | 'in' | 'no_access' | 'hub_down';

interface AuthContextType {
    user: User | null;
    state: AuthState;
    logout: () => Promise<void>;
    refreshUser: () => Promise<void>;
    retry: () => void;
    isLoading: boolean;
}

const AuthContext = createContext<AuthContextType | null>(null);

interface Found { user: User | null; state: AuthState }

// Who is logged in; not logged in: the API client already sends the browser to the hub's login
async function whoIsLoggedIn(): Promise<Found> {
    try {
        const response = await api.get<User>('/api/v1/me');
        return { user: response.data, state: 'in' };
    } catch (err) {
        const code = errorCode(err);
        if (code === 'not_logged_in') return { user: null, state: 'loading' };
        return { user: null, state: code === 'no_access' ? 'no_access' : 'hub_down' };
    }
}

// The login is the family hub's (spec 2026-10-30): the browser carries its cookie; without one the hub asks for the PIN
export const AuthProvider = ({ children }: { children: ReactNode }) => {
    const [user, setUser] = useState<User | null>(null);
    const [state, setState] = useState<AuthState>('loading');

    const apply = useCallback((found: Found) => {
        if (found.user) {
            applyLanguage(found.user.language);
            setUser(found.user);
        }
        setState(found.state);
    }, []);

    useEffect(() => {
        let current = true;
        whoIsLoggedIn().then(found => { if (current) apply(found); });
        return () => { current = false; };
    }, [apply]);

    // Reload the current user after their settings change on the server
    const refreshUser = async () => {
        const response = await api.get('/api/v1/me');
        applyLanguage(response.data.language);
        setUser(response.data);
    };

    // Logs out in the family hub: that ends the login for every family app, then shows the hub's login
    const logout = async () => {
        await goToHubLogout();
    };

    return (
        <AuthContext.Provider value={{ user, state, logout, refreshUser, retry: () => { setState('loading'); void whoIsLoggedIn().then(apply); }, isLoading: state === 'loading' }}>
            {children}
        </AuthContext.Provider>
    );
};

// eslint-disable-next-line react-refresh/only-export-components -- the hook belongs with its provider
export const useAuth = () => {
    const context = useContext(AuthContext);
    if (!context) {
        throw new Error('useAuth must be used within an AuthProvider');
    }
    return context;
};
