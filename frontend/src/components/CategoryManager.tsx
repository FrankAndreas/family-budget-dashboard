import { useEffect, useState } from 'react';
import api, { errorMessage } from '../api';
import type { Category } from '../accounts';

type Usage = Record<string, { transactions: number; budgets: number; planned_costs: number; import_rules: number }>;

const GROUPS = [
    { type: 'INCOME', label: 'Income' },
    { type: 'EXPENSE', label: 'Expenses' },
    { type: 'TRANSFER', label: 'Transfers' },
];

const WORDS: [keyof Usage[string], string, string][] = [
    ['transactions', 'transaction', 'transactions'],
    ['budgets', 'budget', 'budgets'],
    ['planned_costs', 'yearly bill or monthly cost', 'yearly bills or monthly costs'],
    ['import_rules', 'import rule', 'import rules'],
];

// "used by 2 transactions, 1 budget"
const describe = (counts?: Usage[string]) => counts
    ? 'used by ' + WORDS.filter(([key]) => counts[key]).map(([key, one, many]) => `${counts[key]} ${counts[key] === 1 ? one : many}`).join(', ')
    : '';

const field = 'p-2 rounded bg-slate-800/50 border border-slate-600 text-white';

// Settings → Categories (parents): add, rename, retype and delete; the app's own categories (🔒) only change icon
export default function CategoryManager() {
    const [categories, setCategories] = useState<Category[]>([]);
    const [usage, setUsage] = useState<Usage>({});
    const [form, setForm] = useState({ name: '', type: 'EXPENSE', icon: '' });
    const [editing, setEditing] = useState<{ id: string; name: string; type: string; icon: string } | null>(null);
    const [error, setError] = useState('');
    const [version, setVersion] = useState(0);

    useEffect(() => {
        Promise.all([api.get('/api/v1/categories'), api.get('/api/v1/categories/usage')])
            .then(([c, u]) => {
                setCategories(c.data);
                setUsage(u.data);
            })
            .catch(err => setError(errorMessage(err, 'Failed to load categories')));
    }, [version]);

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
        if (await change(api.post('/api/v1/categories', { ...form, icon: form.icon || null }), 'Failed to add the category')) {
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
        if (await change(api.put(`/api/v1/categories/${editing.id}`, body), 'Failed to save the category')) {
            setEditing(null);
        }
    };

    const remove = (category: Category) => {
        if (!confirm(`Delete the category "${category.name}"?`)) return;
        change(api.delete(`/api/v1/categories/${category.id}`), 'Failed to delete the category');
    };

    const sorted = (type: string) => categories
        .filter(c => c.type === type)
        .sort((a, b) => a.name.localeCompare(b.name));

    return (
        <section className="glass-card p-6">
            <h2 className="text-xl font-bold mb-1">Categories</h2>
            <p className="text-sm text-slate-400 mb-4">
                For bookings, budgets, yearly bills and import rules. 🔒 Categories the app itself uses keep their name;
                a category can only be deleted while nothing uses it.
            </p>
            {error && <p className="text-red-400 text-sm mb-3">{error}</p>}

            <form onSubmit={add} className="flex flex-wrap gap-2 mb-6">
                <input aria-label="New category name" placeholder="New category" value={form.name} maxLength={50} required
                    onChange={e => setForm({ ...form, name: e.target.value })} className={`${field} flex-1 min-w-40`} />
                <select aria-label="New category type" value={form.type}
                    onChange={e => setForm({ ...form, type: e.target.value })} className={field}>
                    <option value="EXPENSE">Expense</option>
                    <option value="INCOME">Income</option>
                </select>
                <input aria-label="New category icon" placeholder="Icon (emoji)" value={form.icon} maxLength={8}
                    onChange={e => setForm({ ...form, icon: e.target.value })} className={`${field} w-32`} />
                <button type="submit" className="btn-primary text-sm">Add category</button>
            </form>

            {GROUPS.map(group => (
                <div key={group.type} className="mb-4">
                    <h3 className="font-semibold mb-2">{group.label}</h3>
                    <ul className="space-y-1">
                        {sorted(group.type).map(category => {
                            const used = describe(usage[category.id]);
                            return (
                                <li key={category.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 p-2 rounded bg-slate-800/30 text-sm">
                                    {editing?.id === category.id ? (
                                        <form onSubmit={save} className="flex flex-wrap gap-2 flex-1">
                                            <input aria-label={`Icon of ${category.name}`} value={editing.icon} maxLength={8}
                                                onChange={e => setEditing({ ...editing, icon: e.target.value })} className={`${field} w-20`} />
                                            {!category.system_key && (<>
                                                <input aria-label={`Name of ${category.name}`} value={editing.name} maxLength={50} required
                                                    onChange={e => setEditing({ ...editing, name: e.target.value })} className={`${field} flex-1 min-w-40`} />
                                                <select aria-label={`Type of ${category.name}`} value={editing.type} disabled={!!used}
                                                    title={used ? `Its type can't change: ${used}` : undefined}
                                                    onChange={e => setEditing({ ...editing, type: e.target.value })} className={field}>
                                                    <option value="EXPENSE">Expense</option>
                                                    <option value="INCOME">Income</option>
                                                </select>
                                            </>)}
                                            <button type="submit" className="btn-primary text-xs">Save</button>
                                            <button type="button" onClick={() => setEditing(null)} className="text-slate-400 hover:text-white">Cancel</button>
                                        </form>
                                    ) : (<>
                                        <span className="w-6 text-center">{category.icon}</span>
                                        <span className="flex-1">{category.name}{category.system_key && <span title="Used by the app: the name stays"> 🔒</span>}</span>
                                        {used && <span className="text-slate-500">{used}</span>}
                                        <button onClick={() => setEditing({ id: category.id, name: category.name, type: category.type, icon: category.icon ?? '' })}
                                            className="text-slate-500 hover:text-blue-400">Edit</button>
                                        {!category.system_key && !used && (
                                            <button onClick={() => remove(category)} className="text-slate-500 hover:text-red-400">Delete</button>
                                        )}
                                    </>)}
                                </li>
                            );
                        })}
                    </ul>
                </div>
            ))}
        </section>
    );
}
