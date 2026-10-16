import { useState } from 'react';
import api, { errorMessage } from '../api';
import { useAuth } from '../AuthContext';

// Settings → Logins: end every login of yours, on every device (e.g. a lost phone)
export default function Logins() {
    const { logout } = useAuth();
    const [error, setError] = useState('');

    const logoutEverywhere = async () => {
        if (!confirm('Log out on every device, this one included?')) return;
        try {
            await api.post('/api/v1/me/logout-everywhere');
            logout();
        } catch (err) {
            setError(errorMessage(err, 'Failed to log out everywhere'));
        }
    };

    return (
        <div className="glass-card p-6">
            <h2 className="text-xl font-bold mb-2">Logins</h2>
            <p className="text-sm text-slate-400 mb-4">
                A login lasts about two days on each device. If a phone or computer gets lost, end all your logins at
                once; you then log in again with your PIN. Changing a PIN does the same for that person.
            </p>
            {error && <p className="text-red-400 text-sm mb-3">{error}</p>}
            <button onClick={logoutEverywhere} className="btn-primary text-sm">Log out everywhere</button>
        </div>
    );
}
