import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import api, { errorMessage } from '../api';
import type { Tag } from '../receipts';

type Usage = Record<string, { items: number; budgets: number }>;

const field = 'p-2 rounded bg-slate-800/50 border border-slate-600 text-white';

// Settings → Tags (parents): what receipt items are for (Velo, Garten, ...), across categories (issue #56)
export default function TagManager() {
    const { t } = useTranslation();
    const [tags, setTags] = useState<Tag[]>([]);
    const [usage, setUsage] = useState<Usage>({});
    const [form, setForm] = useState({ name: '', icon: '' });
    const [editing, setEditing] = useState<{ id: string; name: string; icon: string } | null>(null);
    const [error, setError] = useState('');
    const [version, setVersion] = useState(0);

    useEffect(() => {
        Promise.all([api.get('/api/v1/tags'), api.get('/api/v1/tags/usage')])
            .then(([list, counts]) => {
                setTags(list.data);
                setUsage(counts.data);
            })
            .catch(err => setError(errorMessage(err, t('tags.loadFailed'))));
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
        if (await change(api.post('/api/v1/tags', { name: form.name, icon: form.icon || null }), t('tags.addFailed'))) {
            setForm({ name: '', icon: '' });
        }
    };

    const save = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!editing) return;
        const body = { name: editing.name, icon: editing.icon || null };
        if (await change(api.put(`/api/v1/tags/${editing.id}`, body), t('tags.saveFailed'))) setEditing(null);
    };

    const remove = (tag: Tag) => {
        if (!confirm(t('tags.confirmDelete', { name: tag.name }))) return;
        change(api.delete(`/api/v1/tags/${tag.id}`), t('tags.deleteFailed'));
    };

    const describe = (tag: Tag) => {
        const counts = usage[tag.id];
        if (!counts || (!counts.items && !counts.budgets)) return '';
        return [
            counts.items ? t('tags.usedByItems', { count: counts.items }) : '',
            counts.budgets ? t('tags.usedByBudgets', { count: counts.budgets }) : '',
        ].filter(Boolean).join(', ');
    };

    return (
        <section className="glass-card p-6">
            <h2 className="text-xl font-bold mb-1">{t('tags.title')}</h2>
            <p className="text-sm text-slate-400 mb-4">{t('tags.intro')}</p>
            {error && <p className="text-red-400 text-sm mb-3">{error}</p>}

            <form onSubmit={add} className="flex flex-wrap gap-2 mb-4">
                <input aria-label={t('tags.newName')} placeholder={t('tags.newPlaceholder')} value={form.name}
                    maxLength={50} required onChange={e => setForm({ ...form, name: e.target.value })}
                    className={`${field} flex-1 min-w-40`} />
                <input aria-label={t('tags.newIcon')} placeholder={t('tags.iconPlaceholder')} value={form.icon}
                    maxLength={8} onChange={e => setForm({ ...form, icon: e.target.value })} className={`${field} w-32`} />
                <button type="submit" className="btn-primary text-sm">{t('tags.add')}</button>
            </form>

            {tags.length === 0 && <p className="text-sm text-slate-400">{t('tags.none')}</p>}
            <ul className="space-y-1">
                {tags.map(tag => (
                    <li key={tag.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 p-2 rounded bg-slate-800/30 text-sm">
                        {editing?.id === tag.id ? (
                            <form onSubmit={save} className="flex flex-wrap gap-2 flex-1">
                                <input aria-label={t('tags.iconOf', { name: tag.name })} value={editing.icon} maxLength={8}
                                    onChange={e => setEditing({ ...editing, icon: e.target.value })} className={`${field} w-20`} />
                                <input aria-label={t('tags.nameOf', { name: tag.name })} value={editing.name} maxLength={50} required
                                    onChange={e => setEditing({ ...editing, name: e.target.value })} className={`${field} flex-1 min-w-40`} />
                                <button type="submit" className="btn-primary text-xs">{t('common.save')}</button>
                                <button type="button" onClick={() => setEditing(null)} className="text-slate-400 hover:text-white">{t('common.cancel')}</button>
                            </form>
                        ) : (<>
                            <span className="w-6 text-center">{tag.icon}</span>
                            <span className="flex-1">{tag.name}</span>
                            {describe(tag) && <span className="text-slate-500">{describe(tag)}</span>}
                            <button onClick={() => setEditing({ id: tag.id, name: tag.name, icon: tag.icon ?? '' })}
                                className="text-slate-500 hover:text-blue-400">{t('common.edit')}</button>
                            {!usage[tag.id]?.budgets && (
                                <button onClick={() => remove(tag)} className="text-slate-500 hover:text-red-400">{t('common.delete')}</button>
                            )}
                        </>)}
                    </li>
                ))}
            </ul>
        </section>
    );
}
