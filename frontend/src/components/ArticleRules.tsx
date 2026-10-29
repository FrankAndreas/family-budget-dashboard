import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import api, { errorMessage } from '../api';
import { useTags } from '../receipts';

interface Rule { id: string; name: string; category_id: string; category: string; tag_ids: string[] }
// What a booking proposed; rule: the rule it would change
interface Suggestion extends Rule { rule: { category: string; tag_ids: string[] } | null }
interface Category { id: string; name: string; type: string; system_key?: string | null }

const field = 'p-2 rounded bg-slate-800/50 border border-slate-600 text-white text-sm';

// Article rules: what a receipt article (its whole name) is booked as by the Migros import; learnt on import, a few
// hundred after a while, so the list is searched
export default function ArticleRules({ version }: { version: number }) {
    const { t } = useTranslation();
    const { tags } = useTags();
    const [rules, setRules] = useState<Rule[]>([]);
    const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
    const [categories, setCategories] = useState<Category[]>([]);
    const [query, setQuery] = useState('');
    const [message, setMessage] = useState('');
    const [reload, setReload] = useState(0);
    // The rule being edited, with its new category and tags
    const [editing, setEditing] = useState<Rule | null>(null);

    useEffect(() => {
        api.get('/api/v1/article-rules')
            .then(res => setRules(res.data))
            .catch(err => setMessage(errorMessage(err, t('articleRules.loadFailed'))));
        api.get('/api/v1/article-rules/suggestions')
            .then(res => setSuggestions(res.data))
            .catch(err => setMessage(errorMessage(err, t('articleRules.loadFailed'))));
        api.get('/api/v1/categories').then(res => setCategories(res.data)).catch(() => setCategories([]));
    }, [version, reload, t]);

    const save = async () => {
        if (!editing) return;
        try {
            await api.put(`/api/v1/article-rules/${editing.id}`,
                { name: editing.name, category_id: editing.category_id, tag_ids: editing.tag_ids });
            setEditing(null);
            setMessage('');
            setReload(r => r + 1);
        } catch (err) {
            setMessage(errorMessage(err, t('articleRules.saveFailed')));
        }
    };

    const remove = async (rule: Rule) => {
        if (!confirm(t('articleRules.confirmDelete', { name: rule.name }))) return;
        try {
            await api.delete(`/api/v1/article-rules/${rule.id}`);
            setReload(r => r + 1);
        } catch (err) {
            setMessage(errorMessage(err, t('articleRules.deleteFailed')));
        }
    };

    // A suggestion changed before adding is only changed here; Add sends it
    const changeSuggestion = (id: string, change: Partial<Suggestion>) =>
        setSuggestions(list => list.map(s => (s.id === id ? { ...s, ...change } : s)));

    const act = async (request: () => Promise<unknown>) => {
        try {
            await request();
            setMessage('');
            setReload(r => r + 1);
        } catch (err) {
            setMessage(errorMessage(err, t('articleRules.addFailed')));
        }
    };
    const add = (s: Suggestion) =>
        act(() => api.post(`/api/v1/article-rules/suggestions/${s.id}/add`, { category_id: s.category_id, tag_ids: s.tag_ids }));
    const ignore = (s: Suggestion) => act(() => api.delete(`/api/v1/article-rules/suggestions/${s.id}`));
    const addAll = () => act(() => api.post('/api/v1/article-rules/suggestions/add-all'));
    const expense = categories.filter(c => c.type === 'EXPENSE' && !c.system_key);

    const tagName = (id: string) => tags.find(tag => tag.id === id)?.name ?? '';
    const shown = rules.filter(rule => rule.name.toLowerCase().includes(query.trim().toLowerCase()));

    return (
        <div className="mt-6">
            <h4 className="font-semibold mb-1">{t('articleRules.title')}</h4>
            <p className="text-sm text-slate-400 mb-2">{t('articleRules.intro')}</p>
            {message && <p className="text-sm text-red-300 mb-2">{message}</p>}
            {suggestions.length > 0 && (
                <div className="mb-4 p-3 rounded-lg border border-amber-500/40 bg-amber-500/10">
                    <div className="flex flex-wrap items-center justify-between gap-2 mb-1">
                        <h5 className="font-semibold text-amber-200">{t('articleRules.suggestions', { count: suggestions.length })}</h5>
                        <button className="btn-primary text-xs" onClick={addAll}>{t('articleRules.addAll')}</button>
                    </div>
                    <p className="text-sm text-slate-400 mb-2">{t('articleRules.suggestionsIntro')}</p>
                    <ul className="space-y-2 text-sm">
                        {suggestions.map(s => (
                            <li key={s.id} className="flex flex-wrap items-center gap-2">
                                <span className="min-w-0 break-words font-medium">{s.name}</span>
                                <select className={field} value={s.category_id} aria-label={t('articleRules.suggestionCategory', { name: s.name })}
                                    onChange={e => changeSuggestion(s.id, { category_id: e.target.value })}>
                                    {expense.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                                </select>
                                {tags.map(tag => {
                                    const on = s.tag_ids.includes(tag.id);
                                    return (
                                        <label key={tag.id} className={`px-2 py-0.5 rounded-full text-xs cursor-pointer border ${on
                                            ? 'bg-amber-500/20 border-amber-400 text-amber-200' : 'border-slate-600 text-slate-400'}`}>
                                            <input type="checkbox" className="sr-only" checked={on}
                                                aria-label={t('articleRules.suggestionTag', { tag: tag.name, name: s.name })}
                                                onChange={() => changeSuggestion(s.id, {
                                                    tag_ids: on ? s.tag_ids.filter(id => id !== tag.id) : [...s.tag_ids, tag.id],
                                                })} />
                                            {tag.icon ? `${tag.icon} ` : ''}{tag.name}
                                        </label>
                                    );
                                })}
                                {s.rule && <span className="text-xs text-slate-400">{t('articleRules.changesRule', { category: s.rule.category })}</span>}
                                <button className="text-blue-400 hover:underline" onClick={() => add(s)}
                                    aria-label={t('articleRules.add', { name: s.name })}>{t('articleRules.addShort')}</button>
                                <button className="text-slate-500 hover:text-red-400" onClick={() => ignore(s)}
                                    aria-label={t('articleRules.ignore', { name: s.name })}>{t('articleRules.ignoreShort')}</button>
                            </li>
                        ))}
                    </ul>
                </div>
            )}
            {rules.length === 0 ? (
                <p className="text-sm text-slate-500">{t('articleRules.none')}</p>
            ) : (<>
                <input className={`${field} w-full mb-2`} value={query} onChange={e => setQuery(e.target.value)}
                    aria-label={t('articleRules.search')} placeholder={t('articleRules.search')} />
                {query.trim() === '' ? (
                    <p className="text-sm text-slate-500">{t('articleRules.count', { count: rules.length })}</p>
                ) : shown.length === 0 ? (
                    <p className="text-sm text-slate-500">{t('articleRules.noMatch')}</p>
                ) : (
                    <ul className="space-y-1 text-sm">
                        {shown.map(rule => editing?.id === rule.id ? (
                            <li key={rule.id} className="flex flex-wrap items-center gap-2 p-2 rounded bg-slate-800/30">
                                <span className="min-w-0 break-words">{rule.name}</span>
                                <select className={field} value={editing.category_id} aria-label={t('articleRules.category')}
                                    onChange={e => setEditing({ ...editing, category_id: e.target.value })}>
                                    {categories.filter(c => c.type === 'EXPENSE' && !c.system_key)
                                        .map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                                </select>
                                {tags.map(tag => {
                                    const on = editing.tag_ids.includes(tag.id);
                                    return (
                                        <label key={tag.id} className={`px-2 py-0.5 rounded-full text-xs cursor-pointer border ${on
                                            ? 'bg-amber-500/20 border-amber-400 text-amber-200' : 'border-slate-600 text-slate-400'}`}>
                                            <input type="checkbox" className="sr-only" checked={on}
                                                aria-label={t('articleRules.tag', { tag: tag.name })}
                                                onChange={() => setEditing({
                                                    ...editing,
                                                    tag_ids: on ? editing.tag_ids.filter(id => id !== tag.id) : [...editing.tag_ids, tag.id],
                                                })} />
                                            {tag.icon ? `${tag.icon} ` : ''}{tag.name}
                                        </label>
                                    );
                                })}
                                <button className="btn-primary text-xs" onClick={save}>{t('common.save')}</button>
                                <button className="text-slate-400 hover:text-white" onClick={() => setEditing(null)}>{t('common.cancel')}</button>
                            </li>
                        ) : (
                            <li key={rule.id} className="flex flex-wrap items-center gap-2">
                                <span className="flex-1 min-w-0 break-words">
                                    {rule.name} → {rule.category}
                                    {rule.tag_ids.length > 0 && <span className="text-slate-400"> · {rule.tag_ids.map(tagName).join(', ')}</span>}
                                </span>
                                <button className="text-slate-500 hover:text-blue-400" onClick={() => setEditing(rule)}
                                    aria-label={t('articleRules.edit', { name: rule.name })}>{t('common.edit')}</button>
                                <button className="text-slate-500 hover:text-red-400" onClick={() => remove(rule)}
                                    aria-label={t('articleRules.delete', { name: rule.name })}>{t('common.delete')}</button>
                            </li>
                        ))}
                    </ul>
                )}
            </>)}
        </div>
    );
}
