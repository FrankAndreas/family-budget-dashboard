import { useState } from 'react';
import api, { errorMessage } from '../api';
import { useAuth } from '../AuthContext';
import { useFamily } from '../useFamily';

type Level = 'NONE' | 'VIEW' | 'EDIT';

const LEVELS: Record<Level, string> = {
    NONE: "Don't share",
    VIEW: 'Can view',
    EDIT: 'Can view and manage'
};

// Decide which parent may see (or manage) your accounts, transactions and budgets
export default function ShareSettings() {
    const { user } = useAuth();
    const { users, shares, reload } = useFamily();
    const [error, setError] = useState('');
    const parents = users.filter(u => u.role === 'PARENT' && u.id !== user?.id && u.is_active !== false);
    const isChild = user?.role === 'CHILD';

    // Without a setting, parents see a child's money but not each other's
    const levelFor = (granteeId: string): Level =>
        shares.find(s => s.owner_id === user?.id && s.grantee_id === granteeId)?.level ?? (isChild ? 'VIEW' : 'NONE');

    const setLevel = async (granteeId: string, level: Level) => {
        try {
            await api.put(`/api/v1/shares/${granteeId}`, { level });
            setError('');
            reload();
        } catch (err) {
            setError(errorMessage(err, 'Failed to save sharing'));
        }
    };

    if (!user || parents.length === 0 || (isChild && !user.has_allowance)) return null;

    return (
        <div className="glass-card p-6">
            <h2 className="text-2xl font-bold mb-2">Sharing</h2>
            <p className="text-slate-400 mb-4 text-sm">
                {isChild
                    ? 'Choose what each parent may do with your accounts, transactions and budgets. Privacy mode hides everything from all parents.'
                    : 'Your accounts, transactions and budgets are private. Costs you share go through the Common tab, which both parents always see.'}
            </p>
            {error && <p className="mb-3 text-red-300">{error}</p>}
            <div className="space-y-3">
                {parents.map(parent => (
                    <label key={parent.id} className="flex flex-wrap items-center justify-between gap-3 p-4 bg-slate-800/30 rounded-lg">
                        <span>Share my finances with <strong>{parent.username}</strong></span>
                        <select
                            value={levelFor(parent.id)}
                            onChange={(e) => setLevel(parent.id, e.target.value as Level)}
                            className="p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
                        >
                            {(Object.keys(LEVELS) as Level[]).map(level => (
                                <option key={level} value={level}>{LEVELS[level]}</option>
                            ))}
                        </select>
                    </label>
                ))}
            </div>
        </div>
    );
}
