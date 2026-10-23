import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import api, { errorMessage } from '../api';
import type { Account, Category, Transaction } from '../accounts';
import type { FamilyUser } from '../family';
import { money } from '../finance';
import { type AttachmentInfo, type Draft, type Item, openAttachment, useTags } from '../receipts';

interface Props {
    account: Account;
    // Expense categories only: items are costs
    categories: Category[];
    // Whom an item can be for
    people: FamilyUser[];
    // Reading with the AI is set up on the server
    aiEnabled: boolean;
    // Editing an existing booking (its items, or splitting a plain expense into items)
    transaction?: Transaction;
    // A released receipt mail (issue #57): the AI's draft (if any) and the mail as a pending attachment
    draft?: Draft | null;
    attachment?: AttachmentInfo;
    onSaved: () => void;
    onCancel: () => void;
}

interface Row extends Omit<Item, 'amount'> {
    amount: string;
}

const field = 'p-2 rounded bg-slate-800/50 border border-slate-600 text-white';
const MAX_SIDE = 1600;
const today = () => new Date().toISOString().slice(0, 10);

// A photo is shrunk in the browser before upload (receipts don't need more than 1600 px)
async function shrink(file: File): Promise<Blob> {
    if (!file.type.startsWith('image/')) return file;
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext('2d')?.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    return new Promise(resolve => canvas.toBlob(blob => resolve(blob ?? file), 'image/jpeg', 0.85));
}

const toRow = (item: Item): Row => ({ ...item, amount: item.amount.toFixed(2), person_id: item.person_id ?? null });

// A receipt as one booking with its items (issue #56): read by the AI or typed in, checked here, then booked
export default function ReceiptForm({ account, categories, people, aiEnabled, transaction, draft, attachment, onSaved, onCancel }: Props) {
    const { t } = useTranslation();
    const { tags } = useTags();
    const existing = transaction?.items?.length ? transaction.items : undefined;
    const [rows, setRows] = useState<Row[]>(
        existing?.map(toRow)
        ?? draft?.items.map(toRow)
        ?? (transaction ? [{ name: transaction.description || '', amount: Math.abs(transaction.amount).toFixed(2),
            category_id: transaction.category_id, person_id: null, tag_ids: [] }] : [])
    );
    const [description, setDescription] = useState(transaction?.description ?? draft?.shop ?? '');
    const [date, setDate] = useState(transaction ? transaction.date.slice(0, 10)
        : draft && /^\d{4}-\d{2}-\d{2}$/.test(draft.date) ? draft.date : today());
    const [total, setTotal] = useState<number | null>(draft?.total ?? null);
    const [attachments, setAttachments] = useState<AttachmentInfo[]>(
        transaction?.attachments ?? (attachment ? [attachment] : []));
    const [pendingIds, setPendingIds] = useState<string[]>(attachment ? [attachment.id] : []);
    const [reading, setReading] = useState(false);
    const [error, setError] = useState('');

    const sum = rows.reduce((s, r) => s + (parseFloat(r.amount) || 0), 0);
    // A new receipt may belong to a bank booking imported before it (bank import, part 2)
    const [found, setFound] = useState<Transaction[]>([]);
    const [onto, setOnto] = useState('');
    const canMatch = !transaction && sum > 0 && /^\d{4}-\d{2}-\d{2}$/.test(date);
    useEffect(() => {
        if (!canMatch) return;
        api.get(`/api/v1/accounts/${account.id}/payments`, { params: { date, total: Math.round(sum * 100) / 100 } })
            .then(res => setFound(res.data)).catch(() => setFound([]));
    }, [account.id, canMatch, sum, date]);
    const payments = canMatch ? found : [];
    const difference = total === null ? 0 : Math.round((total - sum) * 100) / 100;
    const defaultCategory = categories.find(c => c.system_key === 'UNSORTED')?.id ?? categories[0]?.id ?? '';

    const update = (index: number, change: Partial<Row>) =>
        setRows(rows.map((row, i) => (i === index ? { ...row, ...change } : row)));
    const setPersonForAll = (personId: string | null) => setRows(rows.map(row => ({ ...row, person_id: personId })));
    const toggleTag = (index: number, tagId: string) => {
        const current = rows[index].tag_ids;
        update(index, { tag_ids: current.includes(tagId) ? current.filter(x => x !== tagId) : [...current, tagId] });
    };

    const upload = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const input = e.target;
        const file = input.files?.[0];
        input.value = '';
        if (!file) return;
        setError('');
        setReading(true);
        try {
            const body = new FormData();
            body.append('file', await shrink(file), file.name);
            if (aiEnabled) {
                const response = await api.post('/api/v1/receipts/read', body);
                const read: Draft = response.data.draft;
                setRows(read.items.map(toRow));
                setDescription(read.shop || description);
                if (/^\d{4}-\d{2}-\d{2}$/.test(read.date)) setDate(read.date);
                setTotal(read.total);
                setPendingIds(ids => [...ids, response.data.attachment_id]);
                setAttachments(list => [...list, { id: response.data.attachment_id, filename: file.name,
                    content_type: file.type, size: file.size }]);
            } else if (transaction) {
                // Without the AI, the file is only kept with the booking
                const response = await api.post(`/api/v1/transactions/${transaction.id}/attachments`, body);
                setAttachments(list => [...list, response.data]);
            } else {
                // A new receipt without the AI: kept as pending, linked when booking
                const response = await api.post('/api/v1/attachments', body);
                setPendingIds(ids => [...ids, response.data.id]);
                setAttachments(list => [...list, response.data]);
            }
        } catch (err) {
            setError(errorMessage(err, t('receipt.readFailed')));
        } finally {
            setReading(false);
        }
    };

    const save = async (e: React.FormEvent) => {
        e.preventDefault();
        const items = rows.map(row => ({
            name: row.name,
            amount: parseFloat(row.amount),
            category_id: row.category_id,
            person_id: row.person_id || null,
            tag_ids: row.tag_ids,
        }));
        const body = { description, date: `${date}T12:00:00`, items, attachment_ids: pendingIds };
        try {
            if (transaction) await api.put(`/api/v1/transactions/${transaction.id}`, body);
            // Onto the bank booking: it keeps the bank's amount, the receipt gives its items
            else if (onto && payments.some(p => p.id === onto)) await api.put(`/api/v1/transactions/${onto}`, body);
            else await api.post('/api/v1/transactions', { ...body, account_id: account.id });
            onSaved();
        } catch (err) {
            setError(errorMessage(err, t('receipt.saveFailed')));
        }
    };

    return (
        <form onSubmit={save} className="mb-4 p-4 bg-slate-800/30 rounded-lg space-y-3">
            <h3 className="font-semibold">{transaction ? t('receipt.editTitle') : t('receipt.title')}</h3>

            <label className="block text-sm text-slate-400">
                {aiEnabled ? t('receipt.fileWithAi') : t('receipt.fileWithoutAi')}
                <input type="file" aria-label={t('receipt.file')} accept="image/*,application/pdf,.eml,message/rfc822"
                    onChange={upload} disabled={reading}
                    className="block mt-1 text-sm text-slate-400" />
            </label>
            {reading && <p className="text-blue-400">{t('receipt.reading')}</p>}
            {attachments.length > 0 && (
                <p className="text-sm flex flex-wrap gap-3">
                    {attachments.map(a => (
                        <button type="button" key={a.id} onClick={() => openAttachment(a)} className="text-sky-400 hover:underline">
                            📎 {a.filename}
                        </button>
                    ))}
                </p>
            )}
            {error && <p className="text-red-400 text-sm">{error}</p>}

            <div className="grid gap-2 md:grid-cols-3">
                <input aria-label={t('receipt.description')} placeholder={t('receipt.description')} value={description}
                    onChange={e => setDescription(e.target.value)} className={field} />
                <input aria-label={t('receipt.date')} type="date" value={date} required
                    onChange={e => setDate(e.target.value)} className={field} />
                <select aria-label={t('receipt.personForAll')} defaultValue="" className={field}
                    onChange={e => setPersonForAll(e.target.value || null)}>
                    <option value="">{t('receipt.personForAll')}</option>
                    {people.map(p => <option key={p.id} value={p.id}>{p.username}</option>)}
                </select>
            </div>

            <ul className="space-y-2">
                {rows.map((row, i) => (
                    <li key={i} className="p-2 rounded bg-slate-900/40 space-y-2">
                        <div className="flex flex-wrap gap-2">
                            <input aria-label={t('receipt.itemName', { n: i + 1 })} value={row.name} required maxLength={120}
                                onChange={e => update(i, { name: e.target.value })} className={`${field} flex-1 min-w-40`} />
                            <input aria-label={t('receipt.itemAmount', { n: i + 1 })} type="number" step="0.01" value={row.amount}
                                required onChange={e => update(i, { amount: e.target.value })} className={`${field} w-28 text-right`} />
                            <select aria-label={t('receipt.itemCategory', { n: i + 1 })} value={row.category_id}
                                onChange={e => update(i, { category_id: e.target.value })} className={field}>
                                {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                            </select>
                            <select aria-label={t('receipt.itemPerson', { n: i + 1 })} value={row.person_id ?? ''}
                                onChange={e => update(i, { person_id: e.target.value || null })} className={field}>
                                <option value="">{t('receipt.noPerson')}</option>
                                {people.map(p => <option key={p.id} value={p.id}>{p.username}</option>)}
                            </select>
                            <button type="button" aria-label={t('receipt.removeItem', { n: i + 1 })}
                                onClick={() => setRows(rows.filter((_, j) => j !== i))} className="text-slate-500 hover:text-red-400">✕</button>
                        </div>
                        {tags.length > 0 && (
                            <div className="flex flex-wrap gap-2 text-xs">
                                {tags.map(tag => (
                                    <label key={tag.id} className={`px-2 py-0.5 rounded-full cursor-pointer border ${row.tag_ids.includes(tag.id)
                                        ? 'bg-amber-500/20 border-amber-400 text-amber-200' : 'border-slate-600 text-slate-400'}`}>
                                        <input type="checkbox" className="sr-only" checked={row.tag_ids.includes(tag.id)}
                                            aria-label={t('receipt.itemTag', { n: i + 1, tag: tag.name })}
                                            onChange={() => toggleTag(i, tag.id)} />
                                        {tag.icon ? `${tag.icon} ` : ''}{tag.name}
                                    </label>
                                ))}
                            </div>
                        )}
                    </li>
                ))}
            </ul>
            <button type="button" className="text-sm text-blue-400 hover:underline"
                onClick={() => setRows([...rows, { name: '', amount: '', category_id: defaultCategory, person_id: null, tag_ids: [] }])}>
                {t('receipt.addItem')}
            </button>

            <p className="text-sm">
                {t('receipt.sum', { amount: money(sum) })}
                {total !== null && <span className="text-slate-400">{t('receipt.total', { amount: money(total) })}</span>}
                {difference !== 0 && <span className="text-red-400">{t('receipt.difference', { amount: money(difference) })}</span>}
            </p>
            {payments.length > 0 && (
                <label className="block text-sm">
                    {t('reconcile.ontoPayment')}
                    <select value={onto} onChange={e => setOnto(e.target.value)} aria-label={t('reconcile.ontoPayment')}
                        className={`${field} block mt-1`}>
                        <option value="">{t('reconcile.newBooking')}</option>
                        {payments.map(p => (
                            <option key={p.id} value={p.id}>
                                {(p.bank_rows?.[0]?.text ?? p.description) || '–'} · {(p.bank_rows?.[0]?.booked_on ?? p.date).slice(0, 10)} · {money(p.amount)}
                            </option>
                        ))}
                    </select>
                </label>
            )}
            <div className="flex gap-2">
                <button type="submit" className="btn-primary" disabled={reading || sum <= 0}>{t('receipt.book')}</button>
                <button type="button" onClick={onCancel} className="px-4 text-slate-400 hover:text-white">{t('common.cancel')}</button>
            </div>
        </form>
    );
}
