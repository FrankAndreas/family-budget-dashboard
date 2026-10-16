import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import api, { errorMessage } from '../api';

interface Rule { id: string; text: string; category: string; category_type: string; toml: string }

// Rules learnt in the import preview ("remember"): the import applies them to unrecognised rows, and the bank
// converter gets them through the JSON Schema. Each can also be copied into converter.toml.
export default function ImportRules({ version }: { version: number }) {
    const { t } = useTranslation();
    const [rules, setRules] = useState<Rule[]>([]);
    const [shown, setShown] = useState<string | null>(null);
    const [message, setMessage] = useState('');
    const [reload, setReload] = useState(0);

    useEffect(() => {
        api.get('/api/v1/import/rules')
            .then(res => setRules(res.data))
            .catch(err => setMessage(errorMessage(err, t('importRules.loadFailed'))));
    }, [version, reload, t]);

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

    return (
        <div className="mb-8">
            <h3 className="text-lg font-semibold mb-2">{t('importRules.title')}</h3>
            <p className="text-slate-400 text-sm mb-3">{t('importRules.intro')}</p>
            {message && <p className="text-sm text-slate-300 mb-2">{message}</p>}
            {rules.length === 0 ? (
                <p className="text-sm text-slate-400">{t('importRules.none')}</p>
            ) : (
                <ul className="space-y-2">
                    {rules.map(rule => (
                        <li key={rule.id} className="p-2 rounded bg-slate-800/30 text-sm">
                            <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                                <span className="flex-1">{rule.text} → {rule.category}</span>
                                <button
                                    onClick={() => setShown(shown === rule.id ? null : rule.id)}
                                    className="text-slate-400 hover:text-white"
                                >
                                    {shown === rule.id ? t('importRules.hide') : t('importRules.show')}
                                </button>
                                <button onClick={() => copy(rule)} className="text-blue-400 hover:underline">{t('importRules.copy')}</button>
                                <button onClick={() => remove(rule)} className="text-slate-500 hover:text-red-400">{t('common.delete')}</button>
                            </div>
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
