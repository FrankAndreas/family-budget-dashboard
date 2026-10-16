import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import api, { errorMessage } from '../api';
import { describeSplit, type Split } from '../finance';
import type { FamilyUser } from '../family';

interface Props {
    splits: Split[];
    parents: FamilyUser[];
    onChange: () => void;
}

const MAX_SPLITS = 4;

// The 2–4 preset ratios shared costs can use, e.g. "Equal" 50/50 or "By income" 70/30
export default function SplitManager({ splits, parents, onChange }: Props) {
    const { t } = useTranslation();
    const [editing, setEditing] = useState<{ id: string | null; name: string; shares: Record<string, string> } | null>(null);
    const [error, setError] = useState('');
    const nameOf = (id: string) => parents.find(p => p.id === id)?.username ?? t('common.formerParent');
    const total = editing ? parents.reduce((sum, p) => sum + (parseInt(editing.shares[p.id] || '0', 10) || 0), 0) : 0;

    const open = (split?: Split) => {
        setError('');
        const even = Math.floor(100 / parents.length);
        setEditing({
            id: split?.id ?? null,
            name: split?.name ?? '',
            // A new split starts evenly divided; the first parent gets any remainder
            shares: Object.fromEntries(parents.map((p, i) => [
                p.id,
                String(split?.shares[p.id] ?? (i === 0 ? 100 - even * (parents.length - 1) : even))
            ]))
        });
    };

    const save = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!editing) return;
        const body = {
            name: editing.name,
            shares: Object.fromEntries(parents.map(p => [p.id, parseInt(editing.shares[p.id] || '0', 10)]))
        };
        try {
            if (editing.id) await api.put(`/api/v1/splits/${editing.id}`, body);
            else await api.post('/api/v1/splits', body);
            setEditing(null);
            onChange();
        } catch (err) {
            setError(errorMessage(err, t('splits.saveFailed')));
        }
    };

    const remove = async (split: Split) => {
        if (!confirm(t('splits.confirmDelete', { name: split.name }))) return;
        try {
            await api.delete(`/api/v1/splits/${split.id}`);
            onChange();
        } catch (err) {
            setError(errorMessage(err, t('splits.deleteFailed')));
        }
    };

    const input = 'p-2 rounded bg-slate-800/50 border border-slate-600 text-white';

    return (
        <div className="glass-card p-6">
            <div className="flex justify-between items-center mb-4">
                <h2 className="text-xl font-bold">{t('splits.title')}</h2>
                {splits.length < MAX_SPLITS && !editing && (
                    <button onClick={() => open()} className="btn-primary text-sm">{t('splits.add')}</button>
                )}
            </div>
            {error && <p className="mb-3 text-red-300">{error}</p>}
            <div className="space-y-2">
                {splits.map(split => (
                    <div key={split.id} className="p-3 bg-slate-800/30 rounded-lg flex flex-wrap justify-between gap-2">
                        <div>
                            <p className="font-semibold">{split.name}</p>
                            <p className="text-sm text-slate-400">{describeSplit(split, nameOf)}</p>
                        </div>
                        <div className="flex gap-3 text-sm">
                            <button onClick={() => open(split)} className="text-slate-400 hover:text-white">{t('common.edit')}</button>
                            <button onClick={() => remove(split)} className="text-slate-400 hover:text-red-400">{t('common.delete')}</button>
                        </div>
                    </div>
                ))}
                {splits.length === 0 && !editing && (
                    <p className="text-slate-400 text-sm">{t('splits.none')}</p>
                )}
            </div>
            {editing && (
                <form onSubmit={save} className="mt-4 p-4 bg-slate-800/30 rounded-lg space-y-3">
                    <input
                        type="text"
                        placeholder={t('splits.namePlaceholder')}
                        value={editing.name}
                        onChange={(e) => setEditing({ ...editing, name: e.target.value })}
                        className={`w-full ${input}`}
                        aria-label={t('splits.name')}
                        required
                    />
                    {parents.map(parent => (
                        <label key={parent.id} className="flex items-center justify-between gap-3">
                            <span>{parent.username}</span>
                            <span className="flex items-center gap-1">
                                <input
                                    type="number"
                                    min="0"
                                    max="100"
                                    step="1"
                                    value={editing.shares[parent.id]}
                                    onChange={(e) => setEditing({ ...editing, shares: { ...editing.shares, [parent.id]: e.target.value } })}
                                    className={`w-20 text-right ${input}`}
                                    aria-label={t('splits.percentOf', { name: parent.username })}
                                />
                                %
                            </span>
                        </label>
                    ))}
                    <p className={`text-sm ${total === 100 ? 'text-slate-400' : 'text-red-300'}`}>{t('splits.total', { total })}</p>
                    <div className="flex gap-2">
                        <button type="submit" className="btn-primary flex-1" disabled={total !== 100}>{t('common.save')}</button>
                        <button type="button" onClick={() => setEditing(null)} className="px-4 text-slate-400 hover:text-white">{t('common.cancel')}</button>
                    </div>
                </form>
            )}
        </div>
    );
}
