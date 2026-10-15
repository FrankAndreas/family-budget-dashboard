import { useState } from 'react';
import axios from 'axios';
import api, { errorMessage } from '../api';
import { downloadBlob } from '../download';

interface PreviewRow {
    line: number;
    status: 'ok' | 'duplicate' | 'error';
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
}

interface Preview {
    rows: PreviewRow[];
    ok: number;
    duplicates: number;
    errors: number;
}

interface Status {
    kind: 'success' | 'error';
    text: string;
}

const STATUS_STYLE: Record<PreviewRow['status'], string> = {
    ok: 'text-emerald-300',
    duplicate: 'text-yellow-300',
    error: 'text-red-300',
};

// The file plus the duplicates the user chose to book anyway, as the import endpoints expect them
const formData = (file: File, include: number[] = []) => {
    const data = new FormData();
    data.append('file', file);
    data.append('include_duplicates', include.join(','));
    return data;
};

// A 400 from the import carries the checked rows, so the preview can show what is wrong
const previewFromError = (error: unknown): Preview | null => {
    const detail = axios.isAxiosError(error) ? error.response?.data?.detail : null;
    return detail && typeof detail === 'object' && Array.isArray(detail.rows) ? detail : null;
};

// onImported: the booked rows changed balances and lists elsewhere in the app
export default function ImportTransactions({ onImported }: { onImported?: () => void }) {
    const [file, setFile] = useState<File | null>(null);
    const [preview, setPreview] = useState<Preview | null>(null);
    const [included, setIncluded] = useState<Set<number>>(new Set());
    const [busy, setBusy] = useState(false);
    const [status, setStatus] = useState<Status | null>(null);

    const reset = () => {
        setFile(null);
        setPreview(null);
        setIncluded(new Set());
    };

    const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const input = e.target;
        const chosen = input.files?.[0];
        // Allow choosing the same file again after fixing it
        input.value = '';
        if (!chosen) return;
        reset();
        setStatus(null);
        setBusy(true);
        try {
            const res = await api.post('/api/v1/import/preview', formData(chosen));
            setFile(chosen);
            setPreview(res.data);
        } catch (error) {
            setStatus({ kind: 'error', text: errorMessage(error, 'Could not read the file') });
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
            const res = await api.post('/api/v1/import', formData(file, [...included]));
            const { imported, skipped } = res.data;
            setStatus({
                kind: 'success',
                text: imported === 0
                    ? 'Nothing was imported: every row is already booked.'
                    : `Imported ${imported} transaction${imported === 1 ? '' : 's'}${skipped ? `; skipped ${skipped} duplicate${skipped === 1 ? '' : 's'}` : ''}.`,
            });
            reset();
            if (imported > 0) onImported?.();
        } catch (error) {
            const rows = previewFromError(error);
            if (rows) setPreview(rows);
            setStatus({ kind: 'error', text: rows ? 'The file has errors; nothing was imported.' : errorMessage(error, 'Import failed') });
        } finally {
            setBusy(false);
        }
    };

    const download = async (path: string, filename: string) => {
        try {
            const res = await api.get(path, { responseType: 'blob' });
            downloadBlob(res.data, filename);
        } catch (error) {
            setStatus({ kind: 'error', text: errorMessage(error, 'Download failed') });
        }
    };

    const count = preview ? preview.ok + included.size : 0;

    return (
        <div className="mb-8">
            <h3 className="text-lg font-semibold mb-4">Import Transactions</h3>
            <p className="text-slate-400 mb-3">
                Book many transactions at once from a CSV or JSON file, e.g. one written by a tool that reads receipts.
                You see a preview first; nothing is booked until you confirm.
            </p>
            <div className="flex flex-wrap gap-3 mb-4 text-sm">
                <button className="text-blue-400 hover:underline" onClick={() => download('/api/v1/import/template.csv', 'budget-import-template.csv')}>
                    CSV template
                </button>
                <button className="text-blue-400 hover:underline" onClick={() => download('/api/v1/import/schema', 'budget-import-schema.json')}>
                    JSON Schema (for AI tools)
                </button>
            </div>

            {status && (
                <div className={`mb-4 p-3 rounded-lg flex justify-between items-center border ${status.kind === 'success'
                    ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-300'
                    : 'bg-red-500/20 border-red-500/50 text-red-300'
                    }`}>
                    <span>{status.text}</span>
                    <button onClick={() => setStatus(null)} className="hover:text-white" aria-label="Dismiss message">✕</button>
                </div>
            )}

            <input
                type="file"
                accept=".csv,.json,text/csv,application/json"
                aria-label="File to import"
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
            {busy && <p className="mt-2 text-blue-400">Checking…</p>}

            {preview && file && (
                <div className="mt-4">
                    <p className="text-sm text-slate-300 mb-2">
                        <strong>{file.name}</strong>: {preview.ok} ready
                        {preview.duplicates > 0 && `, ${preview.duplicates} already booked`}
                        {preview.errors > 0 && <span className="text-red-300">, {preview.errors} with errors</span>}
                    </p>
                    <div className="overflow-x-auto max-h-96 overflow-y-auto border border-slate-700 rounded-lg">
                        <table className="w-full text-sm">
                            <thead className="bg-slate-800/80 sticky top-0">
                                <tr className="text-left text-slate-400">
                                    <th className="p-2">Line</th>
                                    <th className="p-2">Date</th>
                                    <th className="p-2">Account</th>
                                    <th className="p-2">Category</th>
                                    <th className="p-2 text-right">Amount</th>
                                    <th className="p-2">Description</th>
                                    <th className="p-2">Status</th>
                                </tr>
                            </thead>
                            <tbody>
                                {preview.rows.map(row => (
                                    <tr key={row.line} className="border-t border-slate-700/50 align-top">
                                        <td className="p-2 text-slate-500">{row.line}</td>
                                        <td className="p-2 whitespace-nowrap">{row.date}</td>
                                        <td className="p-2">{row.account}{row.owner && ` (${row.owner})`}</td>
                                        <td className="p-2">{row.category}{row.shared && <span className="text-slate-400"> · {row.shared}</span>}</td>
                                        <td className="p-2 text-right whitespace-nowrap">
                                            {row.direction && (
                                                <span className="mr-1 text-xs text-slate-400">{row.direction.trim().toLowerCase() === 'in' ? '→ in' : '← out'}</span>
                                            )}
                                            {row.amount}
                                        </td>
                                        <td className="p-2">{row.description}</td>
                                        <td className={`p-2 ${STATUS_STYLE[row.status]}`}>
                                            {row.status === 'ok' && 'Ready'}
                                            {row.status === 'error' && row.errors.map(e => <div key={e}>{e}</div>)}
                                            {row.status === 'duplicate' && (
                                                <label className="flex items-start gap-2 cursor-pointer">
                                                    <input
                                                        type="checkbox"
                                                        className="mt-1"
                                                        checked={included.has(row.line)}
                                                        onChange={() => toggle(row.line)}
                                                    />
                                                    <span>{row.note}. Import anyway</span>
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
                            Import {count} transaction{count === 1 ? '' : 's'}
                        </button>
                        <button className="text-slate-400 hover:text-white" onClick={reset} disabled={busy}>
                            Cancel
                        </button>
                        {preview.errors > 0 && (
                            <span className="text-sm text-red-300">Fix the errors in the file and choose it again.</span>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}
