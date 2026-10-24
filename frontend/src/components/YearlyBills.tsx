import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import api, { errorMessage } from '../api';
import { useAuth } from '../AuthContext';
import { useFamily } from '../useFamily';
import { accessTo, canWrite } from '../family';
import { money, useSplits, type PlannedCost } from '../finance';
import { formatMonth, monthNames } from '../format';
import { ownerFields, ownerValue } from '../ownership';
import OwnerSelect from './OwnerSelect';
import { useScrollIntoView } from '../useScrollIntoView';

interface Category { id: string; name: string; type: string }

const emptyForm = (userId: string) => ({
    id: null as string | null,
    name: '',
    category_id: '',
    amount: '',
    due_month: String(new Date().getMonth() + 1),
    owner: `owner:${userId}`,
    notes: ''
});

// Bills that come once a year: what's due soon, the yearly total and what to put aside each month
export default function YearlyBills() {
    const { t } = useTranslation();
    const { user } = useAuth();
    const { users, shares } = useFamily();
    const { splits } = useSplits();
    const [bills, setBills] = useState<PlannedCost[]>([]);
    const [categories, setCategories] = useState<Category[]>([]);
    const [form, setForm] = useState<ReturnType<typeof emptyForm> | null>(null);
    const formRef = useScrollIntoView<HTMLFormElement>(form?.id);
    const [error, setError] = useState('');
    const [version, setVersion] = useState(0);

    useEffect(() => {
        Promise.all([api.get('/api/v1/planned-costs', { params: { frequency: 'YEARLY' } }), api.get('/api/v1/categories')])
            .then(([b, c]) => {
                setBills(b.data);
                setCategories(c.data.filter((cat: Category) => cat.type === 'EXPENSE'));
            })
            .catch(err => setError(errorMessage(err, t('bills.loadFailed'))));
    }, [version, t]);

    const nameOf = (id: string) => (id === user?.id ? t('common.you') : users.find(u => u.id === id)?.username ?? '');
    const canChange = (bill: PlannedCost) =>
        !bill.owner_id || (!!user && canWrite(accessTo(user, bill.owner_id, users, shares)));
    const yearly = bills.reduce((sum, b) => sum + b.amount, 0);
    // Per person: their own bills plus their part of common ones
    const perPerson: Record<string, number> = {};
    bills.forEach(b => Object.entries(b.shares).forEach(([id, amount]) => {
        perPerson[id] = (perPerson[id] ?? 0) + amount;
    }));

    const save = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!form) return;
        const body = {
            name: form.name,
            category_id: form.category_id,
            amount: parseFloat(form.amount),
            frequency: 'YEARLY',
            due_month: parseInt(form.due_month, 10),
            notes: form.notes || null,
            ...ownerFields(form.owner)
        };
        try {
            if (form.id) await api.put(`/api/v1/planned-costs/${form.id}`, body);
            else await api.post('/api/v1/planned-costs', body);
            setForm(null);
            setError('');
            setVersion(v => v + 1);
        } catch (err) {
            setError(errorMessage(err, t('bills.saveFailed')));
        }
    };

    const remove = async (bill: PlannedCost) => {
        if (!confirm(t('bills.confirmDelete', { name: bill.name }))) return;
        try {
            await api.delete(`/api/v1/planned-costs/${bill.id}`);
            setVersion(v => v + 1);
        } catch (err) {
            setError(errorMessage(err, t('bills.deleteFailed')));
        }
    };

    const edit = (bill: PlannedCost) => setForm({
        id: bill.id,
        name: bill.name,
        category_id: bill.category_id,
        amount: String(bill.amount),
        due_month: String(bill.due_month),
        owner: ownerValue(bill),
        notes: bill.notes ?? ''
    });

    const input = 'w-full p-2 rounded bg-slate-800/50 border border-slate-600 text-white';

    return (
        <div className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="glass-card p-6">
                    <h3 className="text-sky-400 text-lg font-semibold mb-2">{t('bills.perYear')}</h3>
                    <p className="text-3xl font-bold">{money(yearly)}</p>
                </div>
                <div className="glass-card p-6">
                    <h3 className="text-emerald-400 text-lg font-semibold mb-2">{t('bills.putAside')}</h3>
                    {Object.keys(perPerson).length === 0 ? <p className="text-3xl font-bold">{money(0)}</p> : (
                        Object.entries(perPerson).map(([id, amount]) => (
                            <p key={id} className="text-xl font-bold">{nameOf(id)}: {money(amount)}</p>
                        ))
                    )}
                </div>
            </div>

            <div className="glass-card p-6">
                <div className="flex justify-between items-center mb-4">
                    <h2 className="text-2xl font-bold">{t('bills.title')}</h2>
                    {!form && user && (
                        <button onClick={() => setForm(emptyForm(user.id))} className="btn-primary text-sm">{t('bills.add')}</button>
                    )}
                </div>
                {error && <p className="mb-3 text-red-300">{error}</p>}

                {form && (
                    <form ref={formRef} onSubmit={save} className="scroll-mt-4 mb-6 p-4 bg-slate-800/30 rounded-lg grid gap-2 md:grid-cols-2">
                        <input className={input} placeholder={t('bills.namePlaceholder')} value={form.name}
                            onChange={(e) => setForm({ ...form, name: e.target.value })} aria-label={t('bills.name')} required />
                        <input className={input} type="number" step="0.01" min="0.01" placeholder={t('bills.amountPlaceholder')} value={form.amount}
                            onChange={(e) => setForm({ ...form, amount: e.target.value })} aria-label={t('bills.amount')} required />
                        <select className={input} value={form.category_id}
                            onChange={(e) => setForm({ ...form, category_id: e.target.value })} aria-label={t('bills.category')} required>
                            <option value="">{t('bills.selectCategory')}</option>
                            {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                        </select>
                        <select className={input} value={form.due_month}
                            onChange={(e) => setForm({ ...form, due_month: e.target.value })} aria-label={t('bills.dueMonth')}>
                            {monthNames().map((month, i) => <option key={month} value={i + 1}>{t('bills.dueIn', { month })}</option>)}
                        </select>
                        <OwnerSelect value={form.owner} onChange={(owner) => setForm({ ...form, owner })} />
                        <input className={input} placeholder={t('bills.notesPlaceholder')} value={form.notes}
                            onChange={(e) => setForm({ ...form, notes: e.target.value })} aria-label={t('bills.notes')} />
                        <div className="flex gap-2 md:col-span-2">
                            <button type="submit" className="btn-primary flex-1">{form.id ? t('common.save') : t('bills.addBill')}</button>
                            <button type="button" onClick={() => setForm(null)} className="px-4 text-slate-400 hover:text-white">{t('common.cancel')}</button>
                        </div>
                    </form>
                )}

                {bills.length === 0 ? (
                    <p className="text-slate-400 text-center py-8">{t('bills.none')}</p>
                ) : (
                    <div className="space-y-2">
                        {bills.map(bill => (
                            <div key={bill.id} className={`p-3 rounded-lg flex flex-wrap justify-between gap-2 ${bill.due_soon
                                ? 'bg-amber-500/10 border border-amber-500/40'
                                : 'bg-slate-800/30'}`}>
                                <div>
                                    <p className="font-semibold">
                                        {bill.name}
                                        {bill.due_soon && (
                                            <span className="ml-2 text-xs font-normal px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300">{t('bills.dueSoon')}</span>
                                        )}
                                    </p>
                                    <p className="text-sm text-slate-400">
                                        {t('bills.due', { month: bill.next_due ? formatMonth(bill.next_due) : '' })}
                                        {' · '}
                                        {bill.split_id
                                            ? t('bills.commonSplit', { name: splits.find(s => s.id === bill.split_id)?.name ?? t('bills.splitFallback') })
                                            : nameOf(bill.owner_id ?? '')}
                                    </p>
                                </div>
                                <div className="flex items-center gap-3">
                                    <div className="text-right">
                                        <p className="font-bold">{money(bill.amount)}</p>
                                        <p className="text-xs text-slate-400">{t('common.perMonth', { amount: money(bill.monthly) })}</p>
                                    </div>
                                    {canChange(bill) && (<>
                                        <button onClick={() => edit(bill)} className="text-slate-500 hover:text-blue-400" aria-label={t('bills.edit')}>✎</button>
                                        <button onClick={() => remove(bill)} className="text-slate-500 hover:text-red-400" aria-label={t('bills.delete')}>✕</button>
                                    </>)}
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}
