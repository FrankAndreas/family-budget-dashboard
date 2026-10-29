import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import api, { errorMessage } from '../api';
import { money } from '../finance';
import { formatDate } from '../format';
import { useTags } from '../receipts';
import { migrosForm, receiptDay, type Article, type MigrosPreview, type MigrosReceipt, type ReceiptChoice } from '../migros';

interface Category { id: string; name: string; type: string; system_key?: string | null }

interface Props {
    file: File;
    onImported: (text: string) => void;
    onCancel: () => void;
}

const field = 'p-1 rounded bg-slate-800/50 border border-slate-600 text-white text-sm max-w-full';

// The receipts of a Migros export: each onto its payment or booked new, its articles by rule, AI or fallback; what
// is booked becomes the articles' rules (spec 2026-10-28)
export default function MigrosImport({ file, onImported, onCancel }: Props) {
    const { t } = useTranslation();
    const { tags } = useTags();
    const [categories, setCategories] = useState<Category[]>([]);
    const [preview, setPreview] = useState<MigrosPreview | null>(null);
    const [busy, setBusy] = useState(true);
    const [error, setError] = useState('');
    // What the AI did on the first look (later looks don't ask it), kept while its fallbacks are shown
    const [aiNote, setAiNote] = useState<MigrosPreview['ai']>(null);
    // What the person changed on receipts; the server fits the rest around it
    const [changed, setChanged] = useState<Record<string, Partial<ReceiptChoice>>>({});

    // The first look asks the AI once; later ones send its answers back as the articles
    useEffect(() => {
        let gone = false;
        api.get('/api/v1/categories').then(res => !gone && setCategories(res.data)).catch(() => undefined);
        api.post('/api/v1/import/migros/preview', migrosForm(file, {}, {}, true))
            .then(res => {
                if (gone) return;
                setPreview(res.data);
                setAiNote(res.data.ai);
            })
            .catch(err => !gone && setError(errorMessage(err, t('migros.readFailed'))))
            .finally(() => !gone && setBusy(false));
        return () => { gone = true; };
    }, [file, t]);

    const again = async (articles: Record<string, Article>, receipts: Record<string, Partial<ReceiptChoice>>) => {
        setChanged(receipts);
        setBusy(true);
        try {
            const res = await api.post('/api/v1/import/migros/preview', migrosForm(file, articles, receipts));
            setPreview(res.data);
            setError('');
        } catch (err) {
            setError(errorMessage(err, t('migros.changeFailed')));
        } finally {
            setBusy(false);
        }
    };

    if (!preview) {
        return <p className="mt-4 text-sm">{busy ? t('importing.checking') : <span className="text-red-300">{error}</span>}</p>;
    }

    // A payment chosen here is no longer another receipt's choice
    const changeReceipt = (receipt: MigrosReceipt, change: Partial<ReceiptChoice>) => {
        const next = Object.fromEntries(Object.entries(changed).map(([key, choice]) => [key,
            change.payment && change.payment !== 'new' && choice.payment === change.payment
                ? { ...choice, payment: undefined } : choice]));
        again(preview.articles, { ...next, [receipt.key]: { ...next[receipt.key], ...change } });
    };
    const changeArticle = (key: string, change: Partial<Article>) =>
        again({ ...preview.articles, [key]: { ...preview.articles[key], ...change, source: 'change' } }, changed);

    const runImport = async () => {
        setBusy(true);
        try {
            const res = await api.post('/api/v1/import/migros', migrosForm(file, preview.articles, changed));
            onImported(t('migros.imported', { onto: res.data.onto_payments, booked: res.data.booked, rules: res.data.rules }));
        } catch (err) {
            setError(errorMessage(err, t('migros.importFailed')));
            setBusy(false);
        }
    };

    // The family's expense categories, and whatever a line will be booked as (Unsorted when Groceries is gone)
    const choicesFor = (categoryId: string) =>
        categories.filter(c => c.type === 'EXPENSE' && (!c.system_key || c.id === categoryId));
    const count = preview.receipts.filter(r => r.include).length;
    const label = (r: MigrosReceipt) => `${receiptDay(r.date)} ${r.store}`;

    return (
        <div className="mt-4 space-y-3">
            <p className="text-sm text-slate-300">
                <strong>{file.name}</strong>: {t('migros.summary', { count: preview.receipts.length })}
                {' · '}{t('migros.newRules', { count: preview.new_rules })}
                {aiNote && aiNote.status !== 'ok' && (
                    <span className="block text-amber-300">{aiNote.message ?? t(`migros.ai.${aiNote.status}`)}</span>
                )}
            </p>
            {error && <p className="text-red-300 text-sm">{error}</p>}
            <ul className="space-y-2">
                {preview.receipts.map(receipt => {
                    const open = receipt.status === 'new' || receipt.status === 'maybe_booked';
                    return (
                        <li key={receipt.key} className="p-2 rounded bg-slate-800/30 border border-slate-700 text-sm">
                            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                                <input type="checkbox" checked={receipt.include} disabled={!open || busy}
                                    aria-label={t('migros.include', { receipt: label(receipt) })}
                                    onChange={e => changeReceipt(receipt, { include: e.target.checked })} />
                                <span>{formatDate(receipt.date)} {receipt.time.slice(0, 5)}</span>
                                <strong className="font-semibold">{money(receipt.total)}</strong>
                                {receipt.status === 'imported' && <span className="text-slate-400">{t('migros.status.imported')}</span>}
                                {receipt.status === 'maybe_booked' && <span className="text-amber-300">{t('migros.status.maybe_booked')}</span>}
                                {receipt.status === 'error' && <span className="text-red-300">{receipt.error}</span>}
                                {open && (receipt.payments.length > 0 ? (
                                    <select className={field} value={receipt.payment} disabled={busy}
                                        aria-label={t('migros.payment', { receipt: label(receipt) })}
                                        onChange={e => changeReceipt(receipt, { payment: e.target.value })}>
                                        {receipt.payments.map(p => (
                                            <option key={p.id} value={p.id}>
                                                {t('migros.onto', { text: p.description ?? '', date: formatDate(p.date), amount: money(-p.amount) })}
                                            </option>
                                        ))}
                                        <option value="new">{t('migros.bookNew')}</option>
                                    </select>
                                ) : null)}
                                {open && receipt.payment === 'new' && (
                                    <select className={field} value={receipt.account_id ?? ''} disabled={busy}
                                        aria-label={t('migros.account', { receipt: label(receipt) })}
                                        onChange={e => changeReceipt(receipt, { account_id: e.target.value })}>
                                        {preview.accounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
                                    </select>
                                )}
                            </div>
                            <details className="mt-1">
                                <summary className="cursor-pointer text-slate-300">
                                    {receipt.store} · {t('migros.lines', { count: receipt.lines.length })}
                                </summary>
                                <ul className="mt-2 space-y-2">
                                    {/* Two vouchers of the same name are two lines */}
                                    {receipt.lines.map((line, index) => (
                                        <li key={`${line.key}-${index}`} className="flex flex-wrap items-center gap-x-2 gap-y-1">
                                            <span className="min-w-0 break-words">{line.name}</span>
                                            <span className="text-slate-400">{money(line.amount)}</span>
                                            {line.source === 'discount' ? (
                                                <span className="text-slate-500">{t('migros.source.discount')}</span>
                                            ) : (<>
                                                <select className={field} value={line.category_id} disabled={busy}
                                                    aria-label={t('migros.category', { name: line.name })}
                                                    onChange={e => changeArticle(line.key, { category_id: e.target.value })}>
                                                    {choicesFor(line.category_id).map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                                                </select>
                                                <span className="text-xs text-slate-500">{t(`migros.source.${line.source}`)}</span>
                                                {tags.map(tag => {
                                                    const on = line.tag_ids.includes(tag.id);
                                                    return (
                                                        <label key={tag.id} className={`px-2 py-0.5 rounded-full text-xs cursor-pointer border ${on
                                                            ? 'bg-amber-500/20 border-amber-400 text-amber-200' : 'border-slate-600 text-slate-400'}`}>
                                                            <input type="checkbox" className="sr-only" checked={on} disabled={busy}
                                                                aria-label={t('migros.tag', { name: line.name, tag: tag.name })}
                                                                onChange={() => changeArticle(line.key, {
                                                                    tag_ids: on ? line.tag_ids.filter(id => id !== tag.id) : [...line.tag_ids, tag.id],
                                                                })} />
                                                            {tag.icon ? `${tag.icon} ` : ''}{tag.name}
                                                        </label>
                                                    );
                                                })}
                                            </>)}
                                        </li>
                                    ))}
                                </ul>
                            </details>
                        </li>
                    );
                })}
            </ul>
            <div className="flex flex-wrap gap-2">
                <button className="btn-primary" disabled={busy || count === 0} onClick={runImport}>
                    {t('migros.import', { count })}
                </button>
                <button className="px-4 text-slate-400 hover:text-white" onClick={onCancel}>{t('common.cancel')}</button>
            </div>
        </div>
    );
}
