import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import api, { errorMessage } from '../api';
import { useAuth } from '../AuthContext';
import { useFamily } from '../useFamily';
import { accessTo, canWrite } from '../family';
import { money, useAssets, useSplits, type Asset } from '../finance';
import { formatDate } from '../format';
import { ownerFields, ownerValue } from '../ownership';
import OwnerSelect from './OwnerSelect';
import { useScrollIntoView } from '../useScrollIntoView';

interface Expense { id: string; amount: number; date: string; description: string | null }
type Filter = 'all' | 'mine' | 'common' | 'others';
const FILTERS: Filter[] = ['all', 'mine', 'common', 'others'];

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
    const { t } = useTranslation();
    const { user } = useAuth();
    const { users, shares } = useFamily();
    const { splits } = useSplits();
    const { assets, reload } = useAssets();
    const [filter, setFilter] = useState<Filter>('all');
    const [form, setForm] = useState<ReturnType<typeof emptyForm> | null>(null);
    const [openId, setOpenId] = useState<string | null>(null);
    const [expenses, setExpenses] = useState<Expense[]>([]);
    const [error, setError] = useState('');
    const formRef = useScrollIntoView<HTMLFormElement>(form?.id);

    const ownerLabel = (asset: Asset) => {
        if (asset.split_id) {
            return t('investments.commonSplit', { name: splits.find(s => s.id === asset.split_id)?.name ?? t('investments.splitFallback') });
        }
        return asset.owner_id === user?.id
            ? t('investments.mine')
            : t('investments.someones', { name: users.find(u => u.id === asset.owner_id)?.username ?? '' });
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
            setError(errorMessage(err, t('investments.loadFailed')));
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
            setError(errorMessage(err, t('investments.saveFailed')));
        }
    };

    const remove = async (asset: Asset) => {
        if (!confirm(t('investments.confirmDelete', { name: asset.name }))) return;
        try {
            await api.delete(`/api/v1/assets/${asset.id}`);
            reload();
        } catch (err) {
            setError(errorMessage(err, t('investments.deleteFailed')));
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
                <h2 className="text-2xl font-bold">{t('investments.title')}</h2>
                <div className="flex gap-3">
                    <select
                        value={filter}
                        onChange={(e) => setFilter(e.target.value as Filter)}
                        className="p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
                        aria-label={t('investments.show')}
                    >
                        {FILTERS.map(f => <option key={f} value={f}>{t(`investments.filters.${f}`)}</option>)}
                    </select>
                    {!form && user && (
                        <button onClick={() => setForm(emptyForm(user.id))} className="btn-primary text-sm">{t('investments.add')}</button>
                    )}
                </div>
            </div>
            <p className="text-sm text-slate-400 mb-4">{t('investments.intro')}</p>
            {error && <p className="mb-3 text-red-300">{error}</p>}

            {form && (
                <form ref={formRef} onSubmit={save} className="scroll-mt-4 mb-6 p-4 bg-slate-800/30 rounded-lg grid gap-2 md:grid-cols-2">
                    <input className={input} placeholder={t('investments.namePlaceholder')} value={form.name}
                        onChange={(e) => setForm({ ...form, name: e.target.value })} aria-label={t('investments.name')} required />
                    <input className={input} type="number" step="0.01" min="0.01" placeholder={t('investments.pricePlaceholder')} value={form.price}
                        onChange={(e) => setForm({ ...form, price: e.target.value })} aria-label={t('investments.price')} required />
                    <label className="text-sm text-slate-400">{t('investments.boughtOn')}
                        <input className={input} type="date" value={form.purchase_date}
                            onChange={(e) => setForm({ ...form, purchase_date: e.target.value })} required />
                    </label>
                    <label className="text-sm text-slate-400">{t('investments.lifespan')}
                        <input className={input} type="number" min="1" max="100" step="1" value={form.lifespan_years}
                            onChange={(e) => setForm({ ...form, lifespan_years: e.target.value })} required />
                    </label>
                    <OwnerSelect value={form.owner} onChange={(owner) => setForm({ ...form, owner })} />
                    <input className={input} placeholder={t('investments.notesPlaceholder')} value={form.notes}
                        onChange={(e) => setForm({ ...form, notes: e.target.value })} aria-label={t('investments.notes')} />
                    <div className="flex gap-2 md:col-span-2">
                        <button type="submit" className="btn-primary flex-1">{form.id ? t('common.save') : t('investments.addItem')}</button>
                        <button type="button" onClick={() => setForm(null)} className="px-4 text-slate-400 hover:text-white">{t('common.cancel')}</button>
                    </div>
                </form>
            )}

            {shown.length === 0 ? (
                <p className="text-slate-400 text-center py-8">{t('investments.none')}</p>
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {shown.map(asset => {
                        const used = Math.min(asset.age_years / asset.lifespan_years, 1);
                        return (
                            <div key={asset.id} className="p-4 rounded-lg bg-slate-800/30 border border-slate-700">
                                <div className="flex justify-between gap-2">
                                    <h3 className="font-semibold text-lg">{asset.name}</h3>
                                    {asset.planned && (
                                        <span className="text-xs px-2 py-0.5 h-fit rounded-full bg-sky-500/20 text-sky-300">{t('investments.planned')}</span>
                                    )}
                                    {asset.is_due && (
                                        <span className="text-xs px-2 py-0.5 h-fit rounded-full bg-amber-500/20 text-amber-300">{t('investments.due')}</span>
                                    )}
                                </div>
                                <p className="text-xs text-slate-500">{ownerLabel(asset)}</p>
                                <div className="mt-3 h-2 rounded bg-slate-700" role="img"
                                    aria-label={t('investments.age', { age: asset.age_years, lifespan: asset.lifespan_years })}>
                                    <div className={`h-2 rounded ${asset.is_due ? 'bg-amber-400' : 'bg-cyan-400'}`}
                                        style={{ width: `${used * 100}%` }} />
                                </div>
                                <p className="text-sm text-slate-400 mt-1">
                                    {asset.planned
                                        ? t('investments.plannedFor', { date: formatDate(asset.purchase_date) })
                                        : t('investments.age', { age: asset.age_years, lifespan: asset.lifespan_years })}
                                    {' · '}{t('investments.replace', { year: new Date(asset.replacement_due).getFullYear() })}
                                </p>
                                <p className="mt-2">
                                    {t('investments.setAsideBefore')}<strong>{money(asset.monthly_set_aside)}</strong>{t('investments.setAsideAfter')}
                                </p>
                                <div className="flex gap-3 mt-3 text-sm">
                                    <button onClick={() => toggle(asset)} className="text-slate-400 hover:text-white">
                                        {openId === asset.id ? t('investments.hideCosts') : t('investments.costs')}
                                    </button>
                                    {canChange(asset) && (<>
                                        <button onClick={() => edit(asset)} className="text-slate-400 hover:text-white">{t('common.edit')}</button>
                                        <button onClick={() => remove(asset)} className="text-slate-400 hover:text-red-400">{t('common.delete')}</button>
                                    </>)}
                                </div>
                                {openId === asset.id && (
                                    <div className="mt-3 pt-3 border-t border-slate-700 text-sm space-y-1">
                                        <p>{t('investments.boughtFor', { amount: money(asset.price), date: formatDate(asset.purchase_date) })}</p>
                                        {expenses.map(e => (
                                            <p key={e.id} className="text-slate-400">
                                                {formatDate(e.date)} · {e.description || t('common.noDescription')} · {money(Math.abs(e.amount))}
                                            </p>
                                        ))}
                                        <p className="font-semibold">
                                            {t('investments.total', { total: money(asset.total_cost), perYear: money(asset.cost_per_year) })}
                                        </p>
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
