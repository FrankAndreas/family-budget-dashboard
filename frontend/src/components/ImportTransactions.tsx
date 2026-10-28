import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import axios from 'axios';
import api, { errorMessage } from '../api';
import { useAuth } from '../AuthContext';
import { downloadBlob } from '../download';
import { money } from '../finance';
import { formatDate } from '../format';
import { isMigrosFile } from '../migros';
import MigrosImport from './MigrosImport';

interface PreviewRow {
    line: number;
    status: 'ok' | 'duplicate' | 'error' | 'skipped';
    errors: string[];
    note: string | null;
    date: string;
    account: string;
    owner: string;
    category: string;
    amount: string;
    direction: string;
    description: string;
    shared: string;
    // The category as in the file; category is what will be booked (changed by the user or by a rule)
    file_category: string;
    // The import rule's text when a rule set the category
    rule: string | null;
    // Bank statements only: where the category came from
    source?: 'rule' | 'ai' | 'change' | 'fallback' | null;
    // Bank statements: the bookings this line could confirm, and the one it will (null: a new booking)
    matches?: { id: string; description: string | null; date: string; amount: number }[];
    match?: string | null;
}

// Bank statements: the bank's balance after the file's latest line, and the app's after the import
interface BalanceCheck { account_id: string; account: string; file_balance: number | null; app_balance: number }

interface AiResult {
    status: 'off' | 'ok' | 'capped' | 'limit' | 'failed';
    message: string | null;
    suggestions: Record<string, { category: string; source: 'ai' }>;
}

interface Category { id: string; name: string; type: string }

// A category picked in the preview (or suggested by the AI), and whether to remember it as a rule (parents only)
interface Change { category: string; remember: boolean; text: string; source?: 'ai' }

interface Preview {
    rows: PreviewRow[];
    ok: number;
    duplicates: number;
    errors: number;
    skipped?: number;
    balances?: BalanceCheck[];
    ai?: AiResult;
}

interface Status {
    kind: 'success' | 'error';
    text: string;
}

const STATUS_STYLE: Record<PreviewRow['status'], string> = {
    ok: 'text-emerald-300',
    duplicate: 'text-yellow-300',
    error: 'text-red-300',
    skipped: 'text-slate-500',
};

// The file, the duplicates the user chose to book anyway and the changed categories, as the import endpoints expect them
// (ai: the first preview of a bank statement asks the AI for the rows no rule knows)
const formData = (
    file: File, include: number[] = [], changes: Record<number, Change> = {}, ai = false, matches: Record<number, string> = {},
) => {
    const data = new FormData();
    data.append('file', file);
    data.append('include_duplicates', include.join(','));
    data.append('changes', JSON.stringify(Object.fromEntries(Object.entries(changes).map(
        ([line, c]) => [line, { category: c.category, remember: c.remember ? c.text : '', ...(c.source ? { source: c.source } : {}) }]
    ))));
    if (ai) data.append('ai', '1');
    if (Object.keys(matches).length) data.append('matches', JSON.stringify(matches));
    return data;
};

// A 400 from the import carries the checked rows, so the preview can show what is wrong
const previewFromError = (error: unknown): Preview | null => {
    const detail = axios.isAxiosError(error) ? error.response?.data?.detail : null;
    return detail && typeof detail === 'object' && Array.isArray(detail.rows) ? detail : null;
};

// onImported: the booked rows changed balances and lists elsewhere in the app
export default function ImportTransactions({ onImported }: { onImported?: () => void }) {
    const { t } = useTranslation();
    const { user } = useAuth();
    const [file, setFile] = useState<File | null>(null);
    const [preview, setPreview] = useState<Preview | null>(null);
    const [included, setIncluded] = useState<Set<number>>(new Set());
    const [changes, setChanges] = useState<Record<number, Change>>({});
    // The parent's choice of which booking a bank line confirms ("new": none)
    const [matches, setMatches] = useState<Record<number, string>>({});
    const [categories, setCategories] = useState<Category[]>([]);
    const [busy, setBusy] = useState(false);
    const [status, setStatus] = useState<Status | null>(null);
    // The AI's note for this file (limit reached, failed, ...), kept while its suggestions are
    const [aiMessage, setAiMessage] = useState<string | null>(null);
    // A Migros receipt export: shown by MigrosImport instead of the row preview
    const [migros, setMigros] = useState<File | null>(null);
    // Each choice of a file starts the Migros preview afresh, even for the same file
    const [migrosRound, setMigrosRound] = useState(0);
    const isParent = user?.role === 'PARENT';

    useEffect(() => {
        api.get('/api/v1/categories')
            .then(res => setCategories(res.data))
            .catch(error => setStatus({ kind: 'error', text: errorMessage(error, t('importing.loadCategoriesFailed')) }));
    }, [t]);

    const reset = () => {
        setFile(null);
        setPreview(null);
        setIncluded(new Set());
        setChanges({});
        setMatches({});
        setAiMessage(null);
        setMigros(null);
    };

    const typeOf = (name: string) => categories.find(c => c.name.toLowerCase() === name.trim().toLowerCase())?.type;

    // The sign stays: an expense row may become another expense or Transfer (out); income likewise
    const choicesFor = (row: PreviewRow) => {
        const type = typeOf(row.file_category);
        if (type !== 'EXPENSE' && type !== 'INCOME') return null;
        return [
            ...categories.filter(c => c.type === type).map(c => ({ value: c.name, label: c.name })),
            { value: 'Transfer', label: type === 'EXPENSE' ? t('importing.transferOut') : t('importing.transferIn') }
        ];
    };

    // Check the file again with the changes, so duplicates and errors match what the import will book
    const changeCategory = async (row: PreviewRow, category: string) => {
        if (!file) return;
        const next = { ...changes };
        if (category.toLowerCase() === row.file_category.trim().toLowerCase()) delete next[row.line];
        else next[row.line] = { category, remember: changes[row.line]?.remember ?? false, text: changes[row.line]?.text ?? row.description };
        setChanges(next);
        setBusy(true);
        try {
            const res = await api.post('/api/v1/import/preview', formData(file, [], next, false, matches));
            setPreview(res.data);
        } catch (error) {
            setStatus({ kind: 'error', text: errorMessage(error, t('importing.changeFailed')) });
        } finally {
            setBusy(false);
        }
    };

    const chooseMatch = async (line: number, target: string) => {
        if (!file) return;
        const next = { ...matches, [line]: target };
        setMatches(next);
        setBusy(true);
        try {
            const res = await api.post('/api/v1/import/preview', formData(file, [], changes, false, next));
            setPreview(res.data);
        } catch (error) {
            setStatus({ kind: 'error', text: errorMessage(error, t('importing.changeFailed')) });
        } finally {
            setBusy(false);
        }
    };

    const setRemember = (line: number, update: Partial<Change>) =>
        setChanges({ ...changes, [line]: { ...changes[line], ...update } });

    const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const input = e.target;
        const chosen = input.files?.[0];
        // Allow choosing the same file again after fixing it
        input.value = '';
        if (!chosen) return;
        reset();
        setStatus(null);
        if (await isMigrosFile(chosen)) {
            setMigros(chosen);
            setMigrosRound(round => round + 1);
            return;
        }
        setBusy(true);
        try {
            const res = await api.post('/api/v1/import/preview', formData(chosen, [], {}, true));
            const result: Preview = res.data;
            setFile(chosen);
            setPreview(result);
            if (result.ai) {
                // Kept as changes, so the later previews and the import book what was shown
                const described = Object.fromEntries(result.rows.map(r => [r.line, r.description]));
                setChanges(Object.fromEntries(Object.entries(result.ai.suggestions).map(([line, s]) => [
                    Number(line), { category: s.category, remember: false, text: described[Number(line)] ?? '', source: 'ai' as const },
                ])));
                setAiMessage(result.ai.message);
            }
        } catch (error) {
            setStatus({ kind: 'error', text: errorMessage(error, t('importing.readFailed')) });
        } finally {
            setBusy(false);
        }
    };

    const toggle = (line: number) => {
        const next = new Set(included);
        if (next.has(line)) next.delete(line);
        else next.add(line);
        setIncluded(next);
    };

    const handleImport = async () => {
        if (!file) return;
        setBusy(true);
        try {
            const res = await api.post('/api/v1/import', formData(file, [...included], changes, false, matches));
            const { imported, skipped } = res.data;
            setStatus({
                kind: 'success',
                text: imported === 0
                    ? t('importing.nothingImported')
                    : `${t('importing.imported', { count: imported })}${skipped ? t('importing.skipped', { count: skipped }) : ''}.`,
            });
            reset();
            if (imported > 0) onImported?.();
        } catch (error) {
            const rows = previewFromError(error);
            if (rows) setPreview(rows);
            setStatus({ kind: 'error', text: rows ? t('importing.hasErrors') : errorMessage(error, t('importing.importFailed')) });
        } finally {
            setBusy(false);
        }
    };

    const download = async (path: string, filename: string) => {
        try {
            const res = await api.get(path, { responseType: 'blob' });
            downloadBlob(res.data, filename);
        } catch (error) {
            setStatus({ kind: 'error', text: errorMessage(error, t('importing.downloadFailed')) });
        }
    };

    const count = preview ? preview.ok + included.size : 0;

    return (
        <div className="mb-8">
            <h3 className="text-lg font-semibold mb-4">{t('importing.title')}</h3>
            <p className="text-slate-400 mb-3">{t('importing.intro')}</p>
            <div className="flex flex-wrap gap-3 mb-4 text-sm">
                <button className="text-blue-400 hover:underline" onClick={() => download('/api/v1/import/template.csv', 'budget-import-template.csv')}>
                    {t('importing.csvTemplate')}
                </button>
                <button className="text-blue-400 hover:underline" onClick={() => download('/api/v1/import/schema', 'budget-import-schema.json')}>
                    {t('importing.jsonSchema')}
                </button>
            </div>

            {status && (
                <div className={`mb-4 p-3 rounded-lg flex justify-between items-center border ${status.kind === 'success'
                    ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-300'
                    : 'bg-red-500/20 border-red-500/50 text-red-300'
                    }`}>
                    <span>{status.text}</span>
                    <button onClick={() => setStatus(null)} className="hover:text-white" aria-label={t('importing.dismiss')}>✕</button>
                </div>
            )}

            <input
                type="file"
                accept=".csv,.json,text/csv,application/json"
                aria-label={t('importing.file')}
                onChange={handleFile}
                disabled={busy}
                className="block w-full text-sm text-slate-400
            file:mr-4 file:py-2 file:px-4
            file:rounded file:border-0
            file:text-sm file:font-semibold
            file:bg-blue-500/20 file:text-blue-400
            hover:file:bg-blue-500/30
            file:cursor-pointer cursor-pointer"
            />
            {busy && <p className="mt-2 text-blue-400">{t('importing.checking')}</p>}

            {migros && (
                <MigrosImport key={migrosRound} file={migros}
                    onCancel={() => setMigros(null)}
                    onImported={text => {
                        setMigros(null);
                        setStatus({ kind: 'success', text });
                        onImported?.();
                    }} />
            )}

            {preview && file && (
                <div className="mt-4">
                    <p className="text-sm text-slate-300 mb-2">
                        <strong>{file.name}</strong>: {t('importing.ready', { count: preview.ok })}
                        {preview.duplicates > 0 && t('importing.alreadyBooked', { count: preview.duplicates })}
                        {preview.errors > 0 && <span className="text-red-300">{t('importing.withErrors', { count: preview.errors })}</span>}
                        {(preview.skipped ?? 0) > 0 && t('importing.skippedRows', { count: preview.skipped })}
                    </p>
                    {aiMessage && <p className="text-sm text-amber-300 mb-2">{aiMessage}</p>}
                    {preview.balances && preview.balances.length > 0 && (
                        <ul className="mb-2 text-sm space-y-1">
                            {preview.balances.map(b => {
                                const differs = b.file_balance !== null && Math.abs(b.file_balance - b.app_balance) >= 0.005;
                                return (
                                    <li key={b.account_id} className={differs ? 'text-amber-300' : 'text-slate-300'}>
                                        <strong>{b.account}</strong>: {t('importing.balanceCheck', {
                                            bank: b.file_balance === null ? '–' : money(b.file_balance), app: money(b.app_balance),
                                        })}
                                        {differs && ` ${t('importing.balanceDiffers')}`}
                                    </li>
                                );
                            })}
                        </ul>
                    )}
                    <div className="overflow-x-auto max-h-96 overflow-y-auto border border-slate-700 rounded-lg">
                        <table className="w-full text-sm">
                            <thead className="bg-slate-800/80 sticky top-0">
                                <tr className="text-left text-slate-400">
                                    <th className="p-2">{t('importing.columns.line')}</th>
                                    <th className="p-2">{t('importing.columns.date')}</th>
                                    <th className="p-2">{t('importing.columns.account')}</th>
                                    <th className="p-2">{t('importing.columns.category')}</th>
                                    <th className="p-2 text-right">{t('importing.columns.amount')}</th>
                                    <th className="p-2">{t('importing.columns.description')}</th>
                                    <th className="p-2">{t('importing.columns.status')}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {preview.rows.map(row => (
                                    <tr key={row.line} className="border-t border-slate-700/50 align-top">
                                        <td className="p-2 text-slate-500">{row.line}</td>
                                        <td className="p-2 whitespace-nowrap">{row.date}</td>
                                        <td className="p-2">{row.account}{row.owner && ` (${row.owner})`}</td>
                                        <td className="p-2">
                                            {choicesFor(row) ? (
                                                <select
                                                    value={choicesFor(row)!.find(c => c.value.toLowerCase() === row.category.trim().toLowerCase())?.value ?? row.category}
                                                    onChange={(e) => changeCategory(row, e.target.value)}
                                                    disabled={busy}
                                                    aria-label={t('importing.categoryOfLine', { line: row.line })}
                                                    className="p-1 rounded bg-slate-800/50 border border-slate-600 text-white"
                                                >
                                                    {choicesFor(row)!.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
                                                </select>
                                            ) : row.category}
                                            {row.shared && <span className="text-slate-400"> · {row.shared}</span>}
                                            {row.source === 'ai' && <div className="text-xs text-sky-400">{t('importing.byAi')}</div>}
                                            {changes[row.line] && row.source !== 'ai' && <div className="text-xs text-slate-500">{t('importing.was')}<s>{row.file_category}</s></div>}
                                            {row.rule && <div className="text-xs text-emerald-400">{t('importing.byRule', { rule: row.rule })}</div>}
                                            {row.source === 'fallback' && row.status !== 'error' && !row.match && <div className="text-xs text-slate-500">{t('importing.byFallback')}</div>}
                                            {row.matches && row.matches.length > 0 && (
                                                <select
                                                    value={row.match ?? 'new'}
                                                    onChange={(e) => chooseMatch(row.line, e.target.value)}
                                                    disabled={busy}
                                                    aria-label={t('importing.matchOfLine', { line: row.line })}
                                                    className="mt-1 p-1 rounded bg-slate-800/50 border border-sky-600 text-white text-xs"
                                                >
                                                    {row.matches.map(m => (
                                                        <option key={m.id} value={m.id}>
                                                            {t('importing.confirms', { description: m.description || '–', date: formatDate(m.date), amount: money(m.amount) })}
                                                        </option>
                                                    ))}
                                                    <option value="new">{t('importing.newBooking')}</option>
                                                </select>
                                            )}
                                            {isParent && changes[row.line] && (
                                                <div className="mt-1 flex flex-wrap items-center gap-1 text-xs">
                                                    <label className="flex items-center gap-1 cursor-pointer">
                                                        <input
                                                            type="checkbox"
                                                            checked={changes[row.line].remember}
                                                            onChange={(e) => setRemember(row.line, { remember: e.target.checked })}
                                                            aria-label={t('importing.rememberLine', { line: row.line })}
                                                        />
                                                        {t('importing.rememberFor')}
                                                    </label>
                                                    {changes[row.line].remember && (
                                                        <input
                                                            value={changes[row.line].text}
                                                            onChange={(e) => setRemember(row.line, { text: e.target.value })}
                                                            maxLength={120}
                                                            aria-label={t('importing.ruleTextOfLine', { line: row.line })}
                                                            title={t('importing.ruleTextHint')}
                                                            className="p-1 w-36 rounded bg-slate-800/50 border border-slate-600 text-white"
                                                        />
                                                    )}
                                                </div>
                                            )}
                                        </td>
                                        <td className="p-2 text-right whitespace-nowrap">
                                            {row.direction && (
                                                <span className="mr-1 text-xs text-slate-400">{row.direction.trim().toLowerCase() === 'in' ? t('importing.in') : t('importing.out')}</span>
                                            )}
                                            {row.amount}
                                        </td>
                                        <td className="p-2">{row.description}</td>
                                        <td className={`p-2 ${STATUS_STYLE[row.status]}`}>
                                            {row.status === 'ok' && t('importing.statusReady')}
                                            {row.status === 'skipped' && row.note}
                                            {row.status === 'error' && row.errors.map(e => <div key={e}>{e}</div>)}
                                            {row.status === 'duplicate' && (
                                                <label className="flex items-start gap-2 cursor-pointer">
                                                    <input
                                                        type="checkbox"
                                                        className="mt-1"
                                                        checked={included.has(row.line)}
                                                        onChange={() => toggle(row.line)}
                                                    />
                                                    <span>{t('importing.importAnyway', { note: row.note })}</span>
                                                </label>
                                            )}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                    <div className="flex flex-wrap gap-3 items-center mt-4">
                        <button
                            className="btn-primary disabled:opacity-50"
                            disabled={busy || preview.errors > 0 || count === 0}
                            onClick={handleImport}
                        >
                            {t('importing.importCount', { count })}
                        </button>
                        <button className="text-slate-400 hover:text-white" onClick={reset} disabled={busy}>
                            {t('common.cancel')}
                        </button>
                        {preview.errors > 0 && (
                            <span className="text-sm text-red-300">{t('importing.fixErrors')}</span>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}
