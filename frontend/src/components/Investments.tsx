import { useState } from 'react';
import api, { errorMessage } from '../api';
import { useAuth } from '../AuthContext';
import { useFamily } from '../useFamily';
import { accessTo, canWrite } from '../family';
import { money, useAssets, useSplits, type Asset } from '../finance';
import { ownerFields, ownerValue } from '../ownership';
import OwnerSelect from './OwnerSelect';

interface Expense { id: string; amount: number; date: string; description: string | null }
type Filter = 'all' | 'mine' | 'common' | 'others';

const emptyForm = (userId: string) => ({
    id: null as string | null,
    name: '',
    price: '',
    purchase_date: new Date().toISOString().slice(0, 10),
    lifespan_years: '5',
    owner: `owner:${userId}`,
    notes: ''
});

// Big purchases (TV, fridge, car, bike): age, when to replace them, what to set aside, and what they cost so far
export default function Investments() {
    const { user } = useAuth();
    const { users, shares } = useFamily();
    const { splits } = useSplits();
    const { assets, reload } = useAssets();
    const [filter, setFilter] = useState<Filter>('all');
    const [form, setForm] = useState<ReturnType<typeof emptyForm> | null>(null);
    const [openId, setOpenId] = useState<string | null>(null);
    const [expenses, setExpenses] = useState<Expense[]>([]);
    const [error, setError] = useState('');

    const ownerLabel = (asset: Asset) => {
        if (asset.split_id) return `Common · ${splits.find(s => s.id === asset.split_id)?.name ?? 'split'}`;
        return asset.owner_id === user?.id ? 'Mine' : `${users.find(u => u.id === asset.owner_id)?.username ?? ''}'s`;
    };
    const canChange = (asset: Asset) =>
        !asset.owner_id || (!!user && canWrite(accessTo(user, asset.owner_id, users, shares)));
    const shown = assets.filter(a =>
        filter === 'all' ||
        (filter === 'mine' && a.owner_id === user?.id) ||
        (filter === 'common' && a.split_id) ||
        (filter === 'others' && a.owner_id && a.owner_id !== user?.id)
    );

    const toggle = async (asset: Asset) => {
        if (openId === asset.id) {
            setOpenId(null);
            return;
        }
        try {
            const response = await api.get(`/api/v1/assets/${asset.id}`);
            setExpenses(response.data.expenses);
            setOpenId(asset.id);
        } catch (err) {
            setError(errorMessage(err, 'Failed to load the investment'));
        }
    };

    const save = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!form) return;
        const body = {
            name: form.name,
            price: parseFloat(form.price),
            purchase_date: form.purchase_date,
            lifespan_years: parseInt(form.lifespan_years, 10),
            notes: form.notes || null,
            ...ownerFields(form.owner)
        };
        try {
            if (form.id) await api.put(`/api/v1/assets/${form.id}`, body);
            else await api.post('/api/v1/assets', body);
            setForm(null);
            setError('');
            reload();
        } catch (err) {
            setError(errorMessage(err, 'Failed to save the investment'));
        }
    };

    const remove = async (asset: Asset) => {
        if (!confirm(`Delete "${asset.name}"? Its linked expenses stay as normal expenses.`)) return;
        try {
            await api.delete(`/api/v1/assets/${asset.id}`);
            reload();
        } catch (err) {
            setError(errorMessage(err, 'Failed to delete the investment'));
        }
    };

    const edit = (asset: Asset) => setForm({
        id: asset.id,
        name: asset.name,
        price: String(asset.price),
        purchase_date: asset.purchase_date,
        lifespan_years: String(asset.lifespan_years),
        owner: ownerValue(asset),
        notes: asset.notes ?? ''
    });

    const input = 'w-full p-2 rounded bg-slate-800/50 border border-slate-600 text-white';

    return (
        <div className="glass-card p-6">
            <div className="flex flex-wrap justify-between items-center gap-3 mb-2">
                <h2 className="text-2xl font-bold">Investments</h2>
                <div className="flex gap-3">
                    <select
                        value={filter}
                        onChange={(e) => setFilter(e.target.value as Filter)}
                        className="p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
                        aria-label="Show"
                    >
                        <option value="all">All</option>
                        <option value="mine">Mine</option>
                        <option value="common">Common</option>
                        <option value="others">Others'</option>
                    </select>
                    {!form && user && (
                        <button onClick={() => setForm(emptyForm(user.id))} className="btn-primary text-sm">+ Add Item</button>
                    )}
                </div>
            </div>
            <p className="text-sm text-slate-400 mb-4">
                Link repairs, service or tyres to an item with "For item" when you add the expense.
            </p>
            {error && <p className="mb-3 text-red-300">{error}</p>}

            {form && (
                <form onSubmit={save} className="mb-6 p-4 bg-slate-800/30 rounded-lg grid gap-2 md:grid-cols-2">
                    <input className={input} placeholder="Name, e.g. Car" value={form.name}
                        onChange={(e) => setForm({ ...form, name: e.target.value })} aria-label="Name" required />
                    <input className={input} type="number" step="0.01" min="0.01" placeholder="Price" value={form.price}
                        onChange={(e) => setForm({ ...form, price: e.target.value })} aria-label="Price" required />
                    <label className="text-sm text-slate-400">Bought on
                        <input className={input} type="date" value={form.purchase_date}
                            onChange={(e) => setForm({ ...form, purchase_date: e.target.value })} required />
                    </label>
                    <label className="text-sm text-slate-400">Expected to last (years)
                        <input className={input} type="number" min="1" max="100" step="1" value={form.lifespan_years}
                            onChange={(e) => setForm({ ...form, lifespan_years: e.target.value })} required />
                    </label>
                    <OwnerSelect value={form.owner} onChange={(owner) => setForm({ ...form, owner })} />
                    <input className={input} placeholder="Notes (warranty, serial number, ...)" value={form.notes}
                        onChange={(e) => setForm({ ...form, notes: e.target.value })} aria-label="Notes" />
                    <div className="flex gap-2 md:col-span-2">
                        <button type="submit" className="btn-primary flex-1">{form.id ? 'Save' : 'Add Item'}</button>
                        <button type="button" onClick={() => setForm(null)} className="px-4 text-slate-400 hover:text-white">Cancel</button>
                    </div>
                </form>
            )}

            {shown.length === 0 ? (
                <p className="text-slate-400 text-center py-8">No investments yet</p>
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {shown.map(asset => {
                        const used = Math.min(asset.age_years / asset.lifespan_years, 1);
                        return (
                            <div key={asset.id} className="p-4 rounded-lg bg-slate-800/30 border border-slate-700">
                                <div className="flex justify-between gap-2">
                                    <h3 className="font-semibold text-lg">{asset.name}</h3>
                                    {asset.planned && (
                                        <span className="text-xs px-2 py-0.5 h-fit rounded-full bg-sky-500/20 text-sky-300">Planned</span>
                                    )}
                                    {asset.is_due && (
                                        <span className="text-xs px-2 py-0.5 h-fit rounded-full bg-amber-500/20 text-amber-300">Due</span>
                                    )}
                                </div>
                                <p className="text-xs text-slate-500">{ownerLabel(asset)}</p>
                                <div className="mt-3 h-2 rounded bg-slate-700" role="img"
                                    aria-label={`${asset.age_years} of ${asset.lifespan_years} years`}>
                                    <div className={`h-2 rounded ${asset.is_due ? 'bg-amber-400' : 'bg-cyan-400'}`}
                                        style={{ width: `${used * 100}%` }} />
                                </div>
                                <p className="text-sm text-slate-400 mt-1">
                                    {asset.planned
                                        ? `planned for ${new Date(asset.purchase_date).toLocaleDateString('de-CH')}`
                                        : `${asset.age_years} of ${asset.lifespan_years} years`}
                                    {' · '}replace {new Date(asset.replacement_due).getFullYear()}
                                </p>
                                <p className="mt-2">Set aside <strong>{money(asset.monthly_set_aside)}</strong>/month</p>
                                <div className="flex gap-3 mt-3 text-sm">
                                    <button onClick={() => toggle(asset)} className="text-slate-400 hover:text-white">
                                        {openId === asset.id ? 'Hide costs' : 'Costs'}
                                    </button>
                                    {canChange(asset) && (<>
                                        <button onClick={() => edit(asset)} className="text-slate-400 hover:text-white">Edit</button>
                                        <button onClick={() => remove(asset)} className="text-slate-400 hover:text-red-400">Delete</button>
                                    </>)}
                                </div>
                                {openId === asset.id && (
                                    <div className="mt-3 pt-3 border-t border-slate-700 text-sm space-y-1">
                                        <p>Bought for {money(asset.price)} on {new Date(asset.purchase_date).toLocaleDateString()}</p>
                                        {expenses.map(e => (
                                            <p key={e.id} className="text-slate-400">
                                                {new Date(e.date).toLocaleDateString()} · {e.description || 'No description'} · {money(Math.abs(e.amount))}
                                            </p>
                                        ))}
                                        <p className="font-semibold">Total {money(asset.total_cost)} · {money(asset.cost_per_year)}/year</p>
                                        {asset.notes && <p className="text-slate-400">📝 {asset.notes}</p>}
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}
