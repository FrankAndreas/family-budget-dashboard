import { useEffect, useState } from 'react';
import api, { errorMessage } from '../api';
import { useAuth } from '../AuthContext';
import { useFamily } from '../useFamily';
import { useSplits } from '../finance';
import type { FamilyUser } from '../family';

interface OwnedItem { kind: 'asset' | 'planned'; id: string; name: string }

interface Props {
    member: FamilyUser;
    onDone: (message: string) => void;
    onCancel: () => void;
}

// Removing a family member: decide where each of their investments and yearly bills goes, then confirm
export default function RemoveMember({ member, onDone, onCancel }: Props) {
    const { user } = useAuth();
    const { users } = useFamily();
    const { splits } = useSplits();
    const [items, setItems] = useState<OwnedItem[] | null>(null);
    const [targets, setTargets] = useState<Record<string, string>>({});
    const [error, setError] = useState('');

    useEffect(() => {
        api.get(`/api/v1/users/${member.id}/items`)
            .then(response => setItems(response.data))
            .catch(err => setError(errorMessage(err, 'Failed to load their items')));
    }, [member.id]);

    // Where items can go: another family member, common with a split, or nowhere
    const options = [
        ...users.filter(u => u.id !== member.id).map(u => ({
            value: `owner:${u.id}`,
            label: u.id === user?.id ? 'Me' : u.username
        })),
        ...splits.map(s => ({ value: `split:${s.id}`, label: `Common: ${s.name}` })),
        { value: 'delete', label: 'Delete' }
    ];
    const keyOf = (item: OwnedItem) => `${item.kind}:${item.id}`;
    const allDecided = !!items && items.every(item => targets[keyOf(item)]);

    const moveAll = (value: string) =>
        setTargets(Object.fromEntries((items ?? []).map(item => [keyOf(item), value])));

    const remove = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!items) return;
        const decisions = items.map(item => ({ kind: item.kind, id: item.id, to: targets[keyOf(item)] }));
        try {
            await api.delete(`/api/v1/users/${member.id}`, { data: { items: decisions } });
            onDone(`Removed ${member.username}.`);
        } catch (err) {
            setError(errorMessage(err, 'Failed to remove'));
        }
    };

    const select = 'p-2 rounded bg-slate-800/50 border border-slate-600 text-white';

    return (
        <form onSubmit={remove} className="mt-3 p-4 rounded-lg border border-red-500/40 bg-red-500/10 space-y-3">
            <p className="font-semibold">Remove {member.username} from the family?</p>
            <p className="text-sm text-slate-300">
                Their accounts, transactions, budgets and wishes are deleted. This can't be undone.
            </p>
            {items === null && !error && <p className="text-sm text-slate-400">Loading their items…</p>}
            {items && items.length > 0 && (
                <div className="space-y-2">
                    <p className="text-sm text-slate-300">Where should their investments and yearly bills go?</p>
                    <label className="flex flex-wrap items-center justify-between gap-2 text-sm">
                        <span className="text-slate-400">Move all to</span>
                        <select className={select} defaultValue="" onChange={(e) => moveAll(e.target.value)} aria-label="Move all to">
                            <option value="" disabled>Choose…</option>
                            {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                        </select>
                    </label>
                    {items.map(item => (
                        <label key={keyOf(item)} className="flex flex-wrap items-center justify-between gap-2 p-2 bg-slate-800/30 rounded">
                            <span>{item.kind === 'asset' ? '📦' : '🧾'} {item.name}</span>
                            <select
                                className={select}
                                value={targets[keyOf(item)] ?? ''}
                                onChange={(e) => setTargets({ ...targets, [keyOf(item)]: e.target.value })}
                                aria-label={`Where ${item.name} goes`}
                                required
                            >
                                <option value="" disabled>Choose…</option>
                                {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                            </select>
                        </label>
                    ))}
                </div>
            )}
            {error && <p className="text-red-300 text-sm">{error}</p>}
            <div className="flex gap-2">
                <button
                    type="submit"
                    className="px-4 py-2 rounded-lg bg-red-500/80 hover:bg-red-500 text-white font-semibold disabled:opacity-50"
                    disabled={!allDecided}
                >
                    Remove {member.username}
                </button>
                <button type="button" onClick={onCancel} className="px-4 text-slate-400 hover:text-white">Cancel</button>
            </div>
        </form>
    );
}
