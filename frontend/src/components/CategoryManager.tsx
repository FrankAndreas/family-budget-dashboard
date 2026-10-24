import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import api, { errorMessage } from '../api';
import type { Category } from '../accounts';
import Section from './Section';

type Usage = Record<string, { transactions: number; budgets: number; planned_costs: number; import_rules: number; items: number }>;

// Labels: categories.groups.<type> in the locale files
const GROUPS = ['INCOME', 'EXPENSE', 'TRANSFER'] as const;

const USES = ['transactions', 'budgets', 'planned_costs', 'import_rules', 'items'] as const;

const field = 'p-2 rounded bg-slate-800/50 border border-slate-600 text-white';

// Settings → Categories (parents): add, rename, retype and delete; the app's own categories (🔒) only change icon
export default function CategoryManager() {
    const { t } = useTranslation();
    const [categories, setCategories] = useState<Category[]>([]);
    const [usage, setUsage] = useState<Usage>({});
    const [form, setForm] = useState({ name: '', type: 'EXPENSE', icon: '' });
    const [editing, setEditing] = useState<{ id: string; name: string; type: string; icon: string } | null>(null);
    const [error, setError] = useState('');
    const [version, setVersion] = useState(0);

    // "used by 2 transactions, 1 budget"
    const describe = (counts?: Usage[string]) => counts
        ? t('categories.usedBy', {
            list: USES.filter(use => counts[use]).map(use => t(`categories.usage.${use}`, { count: counts[use] })).join(', '),
        })
        : '';

    useEffect(() => {
        Promise.all([api.get('/api/v1/categories'), api.get('/api/v1/categories/usage')])
            .then(([c, u]) => {
                setCategories(c.data);
                setUsage(u.data);
            })
            .catch(err => setError(errorMessage(err, t('categories.loadFailed'))));
    }, [version, t]);

    const change = async (request: Promise<unknown>, failure: string) => {
        try {
            await request;
            setError('');
            setVersion(v => v + 1);
            return true;
        } catch (err) {
            setError(errorMessage(err, failure));
            return false;
        }
    };

    const add = async (e: React.FormEvent) => {
        e.preventDefault();
        if (await change(api.post('/api/v1/categories', { ...form, icon: form.icon || null }), t('categories.addFailed'))) {
            setForm({ name: '', type: form.type, icon: '' });
        }
    };

    const save = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!editing) return;
        const category = categories.find(c => c.id === editing.id);
        // The app's own categories: only the icon can change
        const body = category?.system_key
            ? { icon: editing.icon || null }
            : { name: editing.name, type: editing.type, icon: editing.icon || null };
        if (await change(api.put(`/api/v1/categories/${editing.id}`, body), t('categories.saveFailed'))) {
            setEditing(null);
        }
    };

    const remove = (category: Category) => {
        if (!confirm(t('categories.confirmDelete', { name: category.name }))) return;
        change(api.delete(`/api/v1/categories/${category.id}`), t('categories.deleteFailed'));
    };

    const sorted = (type: string) => categories
        .filter(c => c.type === type)
        .sort((a, b) => a.name.localeCompare(b.name));

    return (
        <Section id="categories" title={t('categories.title')}>
            <p className="text-sm text-slate-400 mb-4">{t('categories.intro')}</p>
            {error && <p className="text-red-400 text-sm mb-3">{error}</p>}

            <form onSubmit={add} className="flex flex-wrap gap-2 mb-6">
                <input aria-label={t('categories.newName')} placeholder={t('categories.newPlaceholder')} value={form.name} maxLength={50} required
                    onChange={e => setForm({ ...form, name: e.target.value })} className={`${field} flex-1 min-w-40`} />
                <select aria-label={t('categories.newType')} value={form.type}
                    onChange={e => setForm({ ...form, type: e.target.value })} className={field}>
                    <option value="EXPENSE">{t('categories.expense')}</option>
                    <option value="INCOME">{t('categories.income')}</option>
                </select>
                <input aria-label={t('categories.newIcon')} placeholder={t('categories.iconPlaceholder')} value={form.icon} maxLength={8}
                    onChange={e => setForm({ ...form, icon: e.target.value })} className={`${field} w-32`} />
                <button type="submit" className="btn-primary text-sm">{t('categories.add')}</button>
            </form>

            {GROUPS.map(group => (
                <div key={group} className="mb-4">
                    <h3 className="font-semibold mb-2">{t(`categories.groups.${group}`)}</h3>
                    <ul className="space-y-1">
                        {sorted(group).map(category => {
                            const used = describe(usage[category.id]);
                            return (
                                <li key={category.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 p-2 rounded bg-slate-800/30 text-sm">
                                    {editing?.id === category.id ? (
                                        <form onSubmit={save} className="flex flex-wrap gap-2 flex-1">
                                            <input aria-label={t('categories.iconOf', { name: category.name })} value={editing.icon} maxLength={8}
                                                onChange={e => setEditing({ ...editing, icon: e.target.value })} className={`${field} w-20`} />
                                            {!category.system_key && (<>
                                                <input aria-label={t('categories.nameOf', { name: category.name })} value={editing.name} maxLength={50} required
                                                    onChange={e => setEditing({ ...editing, name: e.target.value })} className={`${field} flex-1 min-w-40`} />
                                                <select aria-label={t('categories.typeOf', { name: category.name })} value={editing.type} disabled={!!used}
                                                    title={used ? t('categories.typeLocked', { used }) : undefined}
                                                    onChange={e => setEditing({ ...editing, type: e.target.value })} className={field}>
                                                    <option value="EXPENSE">{t('categories.expense')}</option>
                                                    <option value="INCOME">{t('categories.income')}</option>
                                                </select>
                                            </>)}
                                            <button type="submit" className="btn-primary text-xs">{t('common.save')}</button>
                                            <button type="button" onClick={() => setEditing(null)} className="text-slate-400 hover:text-white">{t('common.cancel')}</button>
                                        </form>
                                    ) : (<>
                                        <span className="w-6 text-center">{category.icon}</span>
                                        <span className="flex-1">{category.name}{category.system_key && <span title={t('categories.locked')}> 🔒</span>}</span>
                                        {used && <span className="text-slate-500">{used}</span>}
                                        <button onClick={() => setEditing({ id: category.id, name: category.name, type: category.type, icon: category.icon ?? '' })}
                                            className="text-slate-500 hover:text-blue-400">{t('common.edit')}</button>
                                        {!category.system_key && !used && (
                                            <button onClick={() => remove(category)} className="text-slate-500 hover:text-red-400">{t('common.delete')}</button>
                                        )}
                                    </>)}
                                </li>
                            );
                        })}
                    </ul>
                </div>
            ))}
        </Section>
    );
}
