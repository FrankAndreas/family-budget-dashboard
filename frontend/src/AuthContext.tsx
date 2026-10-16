import { createContext, useContext, useState, useEffect, type ReactNode } from 'react';
import api from './api';
import { applyLanguage, browserLanguage, type Language } from './i18n';

interface User {
    id: string;
    username: string;
    role: 'PARENT' | 'CHILD';
    privacy_enabled?: boolean;
    has_allowance: boolean;
    language: Language;
}

interface AuthContextType {
    user: User | null;
    login: (username: string, pin: string) => Promise<void>;
    logout: () => void;
    refreshUser: () => Promise<void>;
    isLoading: boolean;
}

const AuthContext = createContext<AuthContextType | null>(null);

export const AuthProvider = ({ children }: { children: ReactNode }) => {
    const [user, setUser] = useState<User | null>(null);
    const [isLoading, setIsLoading] = useState(true);

    // The app speaks the person's own language once they are logged in
    const signedIn = (me: User) => {
        applyLanguage(me.language);
        setUser(me);
    };

    useEffect(() => {
        const checkAuth = async () => {
            const token = localStorage.getItem('token');
            if (token) {
                try {
                    const response = await api.get('/api/v1/me');
                    signedIn(response.data);
                } catch {
                    localStorage.removeItem('token');
                }
            }
            setIsLoading(false);
        };
        checkAuth();
    }, []);

    const login = async (username: string, pin: string) => {
        const response = await api.post('/api/v1/login', { username, pin });
        localStorage.setItem('token', response.data.access_token);
        const userResponse = await api.get('/api/v1/me');
        signedIn(userResponse.data);
    };

    // Reload the current user after their settings change on the server
    const refreshUser = async () => {
        const response = await api.get('/api/v1/me');
        signedIn(response.data);
    };

    const logout = () => {
        localStorage.removeItem('token');
        setUser(null);
        applyLanguage(browserLanguage());
    };

    return (
        <AuthContext.Provider value={{ user, login, logout, refreshUser, isLoading }}>
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
