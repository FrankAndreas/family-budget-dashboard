import { useState } from 'react';
import api, { errorMessage } from '../api';
import { useFamily } from '../useFamily';
import type { FamilyUser } from '../family';

// Parents only: add children and switch them between "dependent" and "own allowance (Jugendlohn)"
export default function FamilyManager() {
    const { users, reload } = useFamily();
    const [newChildName, setNewChildName] = useState('');
    // Child currently being given an own allowance, and the PIN they'll log in with
    const [allowanceChildId, setAllowanceChildId] = useState<string | null>(null);
    const [allowancePin, setAllowancePin] = useState('');
    const [error, setError] = useState('');

    const children = users.filter(u => u.role === 'CHILD');

    const handleAddChild = async (e: React.FormEvent) => {
        e.preventDefault();
        try {
            await api.post('/api/v1/members', { username: newChildName });
            setNewChildName('');
            setError('');
            reload();
        } catch (err) {
            setError(errorMessage(err, 'Failed to add child'));
        }
    };

    const updateChild = async (child: FamilyUser, update: Record<string, unknown>) => {
        try {
            await api.put(`/api/v1/users/${child.id}`, update);
            setAllowanceChildId(null);
            setAllowancePin('');
            setError('');
            reload();
        } catch (err) {
            setError(errorMessage(err, 'Failed to update child'));
        }
    };

    const handleGiveAllowance = (e: React.FormEvent, child: FamilyUser) => {
        e.preventDefault();
        updateChild(child, { has_allowance: true, pin: allowancePin });
    };

    const handleRemoveAllowance = (child: FamilyUser) => {
        if (!confirm(`${child.username} will no longer have own money. Their expenses become household expenses. Continue?`)) return;
        updateChild(child, { has_allowance: false });
    };

    return (
        <div className="glass-card p-6">
            <h2 className="text-2xl font-bold mb-2">Family</h2>
            <p className="text-slate-400 mb-6 text-sm">
                Younger children have no money of their own: their costs are household expenses you can tag with them.
                Once a child gets an own allowance (Jugendlohn), they log in with a PIN and manage their own accounts and budgets.
            </p>

            {error && (
                <div className="mb-4 p-3 bg-red-500/20 border border-red-500/50 rounded-lg text-red-300 flex justify-between items-center">
                    <span>{error}</span>
                    <button onClick={() => setError('')} className="text-red-300 hover:text-white" aria-label="Dismiss error">✕</button>
                </div>
            )}

            <div className="space-y-3 mb-6">
                {children.length === 0 ? (
                    <p className="text-slate-400 text-center py-4">No children added yet</p>
                ) : (
                    children.map(child => (
                        <div key={child.id} className="p-4 bg-slate-800/30 rounded-lg">
                            <div className="flex justify-between items-center gap-4">
                                <div>
                                    <h3 className="font-semibold">{child.username}</h3>
                                    <p className="text-sm text-slate-400">
                                        {child.has_allowance ? 'Own allowance (Jugendlohn)' : 'No own money: costs are household expenses'}
                                    </p>
                                </div>
                                {child.has_allowance ? (
                                    <button
                                        onClick={() => handleRemoveAllowance(child)}
                                        className="text-sm text-slate-400 hover:text-white"
                                    >
                                        Remove allowance
                                    </button>
                                ) : allowanceChildId !== child.id && (
                                    <button
                                        onClick={() => setAllowanceChildId(child.id)}
                                        className="btn-primary text-sm"
                                    >
                                        Give own allowance
                                    </button>
                                )}
                            </div>

                            {allowanceChildId === child.id && (
                                <form onSubmit={(e) => handleGiveAllowance(e, child)} className="mt-3 flex gap-2">
                                    <input
                                        type="password"
                                        inputMode="numeric"
                                        placeholder="PIN for the child (4-6 digits)"
                                        value={allowancePin}
                                        onChange={(e) => {
                                            if (/^\d*$/.test(e.target.value)) setAllowancePin(e.target.value);
                                        }}
                                        minLength={4}
                                        maxLength={6}
                                        className="flex-1 p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
                                        required
                                    />
                                    <button type="submit" className="btn-primary text-sm" disabled={allowancePin.length < 4}>
                                        Save
                                    </button>
                                    <button
                                        type="button"
                                        onClick={() => { setAllowanceChildId(null); setAllowancePin(''); }}
                                        className="px-3 text-slate-400 hover:text-white text-sm"
                                    >
                                        Cancel
                                    </button>
                                </form>
                            )}
                        </div>
                    ))
                )}
            </div>

            <form onSubmit={handleAddChild} className="flex gap-2">
                <input
                    type="text"
                    placeholder="Child's name"
                    value={newChildName}
                    onChange={(e) => setNewChildName(e.target.value)}
                    className="flex-1 p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
                    required
                />
                <button type="submit" className="btn-primary text-sm">+ Add Child</button>
            </form>
        </div>
    );
}
