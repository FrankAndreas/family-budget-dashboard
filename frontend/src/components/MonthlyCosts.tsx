import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import api, { errorMessage } from '../api';
import { money, type PlannedCost, type Split } from '../finance';

interface Category { id: string; name: string; type: string }

// Common costs that come every month (rent, ...); they count in the monthly shares
export default function MonthlyCosts({ splits, onChange }: { splits: Split[]; onChange: () => void }) {
    const { t } = useTranslation();
    const [costs, setCosts] = useState<PlannedCost[]>([]);
    const [categories, setCategories] = useState<Category[]>([]);
    const [form, setForm] = useState<{ id: string | null; name: string; category_id: string; amount: string; split_id: string } | null>(null);
    const [error, setError] = useState('');
    const [version, setVersion] = useState(0);

    useEffect(() => {
        Promise.all([api.get('/api/v1/planned-costs', { params: { frequency: 'MONTHLY' } }), api.get('/api/v1/categories')])
            .then(([c, cats]) => {
                setCosts(c.data);
                setCategories(cats.data.filter((cat: Category) => cat.type === 'EXPENSE'));
            })
            .catch(err => setError(errorMessage(err, t('monthlyCosts.loadFailed'))));
    }, [version, t]);

    const changed = () => {
        setVersion(v => v + 1);
        onChange();
    };

    const save = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!form) return;
        const body = {
            name: form.name,
            category_id: form.category_id,
            amount: parseFloat(form.amount),
            frequency: 'MONTHLY',
            split_id: form.split_id,
            owner_id: null
        };
        try {
            if (form.id) await api.put(`/api/v1/planned-costs/${form.id}`, body);
            else await api.post('/api/v1/planned-costs', body);
            setForm(null);
            setError('');
            changed();
        } catch (err) {
            setError(errorMessage(err, t('monthlyCosts.saveFailed')));
        }
    };

    const remove = async (cost: PlannedCost) => {
        if (!confirm(t('monthlyCosts.confirmDelete', { name: cost.name }))) return;
        try {
            await api.delete(`/api/v1/planned-costs/${cost.id}`);
            changed();
        } catch (err) {
            setError(errorMessage(err, t('monthlyCosts.deleteFailed')));
        }
    };

    const input = 'w-full p-2 rounded bg-slate-800/50 border border-slate-600 text-white';

    return (
        <div className="glass-card p-6">
            <div className="flex justify-between items-center mb-4">
                <h2 className="text-xl font-bold">{t('monthlyCosts.title')}</h2>
                {!form && splits.length > 0 && (
                    <button
                        onClick={() => setForm({ id: null, name: '', category_id: '', amount: '', split_id: splits[0].id })}
                        className="btn-primary text-sm"
                    >
                        {t('monthlyCosts.add')}
                    </button>
                )}
            </div>
            {splits.length === 0 && <p className="text-slate-400 text-sm">{t('monthlyCosts.needsSplit')}</p>}
            {error && <p className="mb-3 text-red-300">{error}</p>}
            {form && (
                <form onSubmit={save} className="mb-4 p-4 bg-slate-800/30 rounded-lg grid gap-2 md:grid-cols-2">
                    <input className={input} placeholder={t('monthlyCosts.namePlaceholder')} value={form.name}
                        onChange={(e) => setForm({ ...form, name: e.target.value })} aria-label={t('monthlyCosts.name')} required />
                    <input className={input} type="number" step="0.01" min="0.01" placeholder={t('monthlyCosts.amountPlaceholder')} value={form.amount}
                        onChange={(e) => setForm({ ...form, amount: e.target.value })} aria-label={t('monthlyCosts.amount')} required />
                    <select className={input} value={form.category_id}
                        onChange={(e) => setForm({ ...form, category_id: e.target.value })} aria-label={t('monthlyCosts.category')} required>
                        <option value="">{t('monthlyCosts.selectCategory')}</option>
                        {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                    </select>
                    <select className={input} value={form.split_id}
                        onChange={(e) => setForm({ ...form, split_id: e.target.value })} aria-label={t('monthlyCosts.split')}>
                        {splits.map(s => <option key={s.id} value={s.id}>{t('monthlyCosts.splitOption', { name: s.name })}</option>)}
                    </select>
                    <div className="flex gap-2 md:col-span-2">
                        <button type="submit" className="btn-primary flex-1">{form.id ? t('common.save') : t('monthlyCosts.addCost')}</button>
                        <button type="button" onClick={() => setForm(null)} className="px-4 text-slate-400 hover:text-white">{t('common.cancel')}</button>
                    </div>
                </form>
            )}
            <div className="space-y-2">
                {costs.map(cost => (
                    <div key={cost.id} className="p-3 bg-slate-800/30 rounded-lg flex justify-between items-center gap-2">
                        <div>
                            <p className="font-semibold">{cost.name}</p>
                            <p className="text-sm text-slate-400">{splits.find(s => s.id === cost.split_id)?.name ?? t('monthlyCosts.splitFallback')}</p>
                        </div>
                        <div className="flex items-center gap-3">
                            <p className="font-bold">{t('common.perMonth', { amount: money(cost.amount) })}</p>
                            <button
                                onClick={() => setForm({
                                    id: cost.id, name: cost.name, category_id: cost.category_id,
                                    amount: String(cost.amount), split_id: cost.split_id ?? splits[0]?.id ?? ''
                                })}
                                className="text-slate-500 hover:text-blue-400"
                                aria-label={t('monthlyCosts.edit')}
                            >
                                ✎
                            </button>
                            <button onClick={() => remove(cost)} className="text-slate-500 hover:text-red-400" aria-label={t('monthlyCosts.delete')}>✕</button>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}
