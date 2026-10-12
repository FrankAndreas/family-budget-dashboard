import { useCallback, useEffect, useMemo, useState } from 'react';
import api from './api';
import { useAuth } from './AuthContext';
import { buildScopes, type FamilyUser } from './family';

// Family members visible to the current user, and the scopes they can switch between
export function useFamily() {
    const { user } = useAuth();
    const [users, setUsers] = useState<FamilyUser[]>([]);
    // Bumped to load the family again after a change
    const [version, setVersion] = useState(0);

    useEffect(() => {
        api.get('/api/v1/users')
            .then(response => setUsers(response.data))
            .catch(error => console.error('Failed to load family members', error));
    }, [version]);

    const reload = useCallback(() => setVersion(v => v + 1), []);

    // Memoized so components can depend on the scopes in effects without reloading every render
    const scopes = useMemo(() => (user && users.length > 0 ? buildScopes(user, users) : []), [user, users]);
    return { users, scopes, reload };
}
