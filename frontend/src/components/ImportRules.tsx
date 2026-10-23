import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import api, { errorMessage } from '../api';

interface Rule {
    id: string; text: string; category: string; category_id: string; category_type: string;
    receipt_expected: boolean; toml: string;
}
interface Category { id: string; name: string; type: string; system_key?: string | null }
interface Form { text: string; category_id: string; receipt_expected: boolean }

const field = 'p-2 rounded bg-slate-800/50 border border-slate-600 text-white';
const empty: Form = { text: '', category_id: '', receipt_expected: false };

// Rules for imported bookings (bank statements and files): text → category, matched as whole words, the longest text
// first. Learnt in the import preview ("remember") or added here; suggested rules for Swiss shops with one button.
// Each can also be copied into converter.toml.
export default function ImportRules({ version }: { version: number }) {
    const { t } = useTranslation();
    const [rules, setRules] = useState<Rule[]>([]);
    const [categories, setCategories] = useState<Category[]>([]);
    const [shown, setShown] = useState<string | null>(null);
    const [message, setMessage] = useState('');
    const [reload, setReload] = useState(0);
    const [form, setForm] = useState<Form>(empty);
    // The rule being edited, with its form
    const [editing, setEditing] = useState<{ id: string; form: Form } | null>(null);

    useEffect(() => {
        api.get('/api/v1/import/rules')
            .then(res => setRules(res.data))
            .catch(err => setMessage(errorMessage(err, t('importRules.loadFailed'))));
        api.get('/api/v1/categories').then(res => setCategories(res.data)).catch(() => setCategories([]));
    }, [version, reload, t]);

    // Income and expense categories, and Transfer (not the ones the app books itself, like settling up)
    const choices = categories
        .filter(c => (c.type !== 'TRANSFER' && !c.system_key) || c.system_key === 'TRANSFER')
        .sort((a, b) => a.name.localeCompare(b.name));

    const copy = async (rule: Rule) => {
        setShown(rule.id);
        try {
            // Only available on https or localhost; otherwise the block stays visible to copy by hand
            await navigator.clipboard.writeText(rule.toml);
            setMessage(t('importRules.copied', { text: rule.text }));
        } catch {
            setMessage(t('importRules.copyImpossible'));
        }
    };

    const add = async (e: React.FormEvent) => {
        e.preventDefault();
        try {
            await api.post('/api/v1/import/rules', form);
            setForm(empty);
            setMessage('');
            setReload(r => r + 1);
        } catch (err) {
            setMessage(errorMessage(err, t('importRules.saveFailed')));
        }
    };

    const save = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!editing) return;
        try {
            await api.put(`/api/v1/import/rules/${editing.id}`, editing.form);
            setEditing(null);
            setMessage('');
            setReload(r => r + 1);
        } catch (err) {
            setMessage(errorMessage(err, t('importRules.saveFailed')));
        }
    };

    const addPresets = async () => {
        try {
            const res = await api.post('/api/v1/import/rules/presets');
            setMessage(t('importRules.presetsAdded', { count: res.data.rules, categories: res.data.categories }));
            setReload(r => r + 1);
        } catch (err) {
            setMessage(errorMessage(err, t('importRules.saveFailed')));
        }
    };

    const remove = async (rule: Rule) => {
        if (!confirm(t('importRules.confirmDelete', { text: rule.text, category: rule.category }))) return;
        try {
            await api.delete(`/api/v1/import/rules/${rule.id}`);
            setMessage('');
            setReload(r => r + 1);
        } catch (err) {
            setMessage(errorMessage(err, t('importRules.deleteFailed')));
        }
    };

    const fields = (value: Form, change: (form: Form) => void) => (<>
        <input value={value.text} onChange={e => change({ ...value, text: e.target.value })} required
            placeholder={t('importRules.textPlaceholder')} aria-label={t('importRules.text')} className={`${field} flex-1 min-w-40`} />
        <select value={value.category_id} onChange={e => change({ ...value, category_id: e.target.value })} required
            aria-label={t('importRules.category')} className={field}>
            <option value="">{t('importRules.chooseCategory')}</option>
            {choices.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <label className="flex items-center gap-1 text-sm">
            <input type="checkbox" checked={value.receipt_expected}
                onChange={e => change({ ...value, receipt_expected: e.target.checked })} />
            {t('importRules.receiptExpected')}
        </label>
    </>);

    return (
        <div className="mb-8">
            <h3 className="text-lg font-semibold mb-2">{t('importRules.title')}</h3>
            <p className="text-slate-400 text-sm mb-3">{t('importRules.intro')}</p>
            <form onSubmit={add} className="flex flex-wrap items-center gap-2 mb-3">
                {fields(form, setForm)}
                <button type="submit" className="btn-primary text-sm">{t('importRules.add')}</button>
            </form>
            <button onClick={addPresets} className="text-sm text-blue-400 hover:underline mb-3">{t('importRules.addPresets')}</button>
            {message && <p className="text-sm text-slate-300 mb-2">{message}</p>}
            {rules.length === 0 ? (
                <p className="text-sm text-slate-400">{t('importRules.none')}</p>
            ) : (
                <ul className="space-y-2">
                    {rules.map(rule => (
                        <li key={rule.id} className="p-2 rounded bg-slate-800/30 text-sm">
                            {editing?.id === rule.id ? (
                                <form onSubmit={save} className="flex flex-wrap items-center gap-2">
                                    {fields(editing.form, f => setEditing({ id: rule.id, form: f }))}
                                    <button type="submit" className="btn-primary text-sm">{t('common.save')}</button>
                                    <button type="button" onClick={() => setEditing(null)} className="text-slate-400 hover:text-white">{t('common.cancel')}</button>
                                </form>
                            ) : (
                                <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                                    <span className="flex-1">
                                        {rule.text} → {rule.category}
                                        {rule.receipt_expected && <span className="ml-2 text-xs text-amber-300">{t('importRules.receiptExpected')}</span>}
                                    </span>
                                    <button onClick={() => setEditing({
                                        id: rule.id,
                                        form: { text: rule.text, category_id: rule.category_id, receipt_expected: rule.receipt_expected },
                                    })} className="text-slate-400 hover:text-white">{t('common.edit')}</button>
                                    <button
                                        onClick={() => setShown(shown === rule.id ? null : rule.id)}
                                        className="text-slate-400 hover:text-white"
                                    >
                                        {shown === rule.id ? t('importRules.hide') : t('importRules.show')}
                                    </button>
                                    <button onClick={() => copy(rule)} className="text-blue-400 hover:underline">{t('importRules.copy')}</button>
                                    <button onClick={() => remove(rule)} className="text-slate-500 hover:text-red-400">{t('common.delete')}</button>
                                </div>
                            )}
                            {shown === rule.id && (
                                <pre className="mt-2 p-2 rounded bg-slate-900/60 text-xs overflow-x-auto select-all">{rule.toml}</pre>
                            )}
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
}
