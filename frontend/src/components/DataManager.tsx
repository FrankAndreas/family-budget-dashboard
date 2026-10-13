import { useState } from 'react';
import api, { errorMessage, fetchAllTransactions } from '../api';
import { useAuth } from '../AuthContext';
import type { FamilyUser } from '../family';

interface ExportAccount {
    id: string;
    name: string;
    type: string;
}

interface ExportCategory {
    id: string;
    name: string;
}

interface ExportBudget {
    category_id: string;
    limit: number;
    period: string;
}

interface ExportTransaction {
    account_id: string;
    category_id: string;
    amount: number;
    description?: string | null;
    date: string;
    member_id?: string | null;
    account_name?: string;
}

interface Status {
    kind: 'success' | 'error';
    text: string;
}

// Quote a CSV field so commas, quotes and line breaks in names don't break the columns
const csvField = (value: string) => `"${value.replace(/"/g, '""')}"`;

const download = (content: string, type: string, extension: string) => {
    const blob = new Blob([content], { type });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `budget-export-${new Date().toISOString().split('T')[0]}.${extension}`;
    a.click();
    URL.revokeObjectURL(url);
};

export default function DataManager() {
    const { user, refreshUser } = useAuth();
    const [importing, setImporting] = useState(false);
    const [exportFormat, setExportFormat] = useState('json');
    const [privacyEnabled, setPrivacyEnabled] = useState(user?.privacy_enabled || false);
    const [savingPrivacy, setSavingPrivacy] = useState(false);
    const [status, setStatus] = useState<Status | null>(null);

    const handleExport = async () => {
        try {
            const [accountsRes, categoriesRes, budgetsRes, usersRes] = await Promise.all([
                api.get('/api/v1/accounts'),
                api.get('/api/v1/categories'),
                api.get('/api/v1/budgets'),
                api.get('/api/v1/users')
            ]);

            const accounts: ExportAccount[] = accountsRes.data;
            const categories: ExportCategory[] = categoriesRes.data;
            const family: FamilyUser[] = usersRes.data;
            const allTransactions: ExportTransaction[] = [];

            // Load all transactions
            for (const account of accounts) {
                try {
                    const accountTransactions = await fetchAllTransactions<ExportTransaction>(account.id);
                    allTransactions.push(...accountTransactions.map(t => ({
                        ...t,
                        account_name: account.name
                    })));
                } catch {
                    console.error('Failed to load transactions for account', account.id);
                }
            }

            if (exportFormat === 'json') {
                const exportData = {
                    exported_at: new Date().toISOString(),
                    accounts,
                    categories,
                    budgets: budgetsRes.data,
                    transactions: allTransactions,
                    // Needed to restore which child a household expense was for
                    family: family.map(({ id, username, role, has_allowance }) => ({ id, username, role, has_allowance }))
                };
                download(JSON.stringify(exportData, null, 2), 'application/json', 'json');
            } else {
                const nameOf = (id: string | null | undefined, list: { id: string; name?: string; username?: string }[]) => {
                    const item = list.find(x => x.id === id);
                    return item?.name ?? item?.username ?? '';
                };
                const csvLines = [
                    'Date,Account,Category,Description,Amount,Type,For',
                    ...allTransactions.map(t => [
                        t.date,
                        csvField(t.account_name ?? ''),
                        csvField(nameOf(t.category_id, categories) || 'Unknown'),
                        csvField(t.description ?? ''),
                        Math.abs(t.amount),
                        t.amount >= 0 ? 'Income' : 'Expense',
                        csvField(nameOf(t.member_id, family))
                    ].join(','))
                ];
                download(csvLines.join('\n'), 'text/csv', 'csv');
            }
            setStatus({ kind: 'success', text: `Exported ${allTransactions.length} transactions.` });
        } catch (error) {
            console.error('Failed to export data', error);
            setStatus({ kind: 'error', text: errorMessage(error, 'Failed to export data') });
        }
    };

    const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const input = e.target;
        const file = input.files?.[0];
        if (!file) return;

        setImporting(true);
        setStatus(null);
        try {
            const data = JSON.parse(await file.text());

            // Category IDs differ between databases, so match the export's categories by name
            const currentCategories: ExportCategory[] = (await api.get('/api/v1/categories')).data;
            const categoryIdByName = new Map(currentCategories.map(c => [c.name, c.id]));
            const categoryMap = new Map<string, string>();
            for (const category of (data.categories || []) as ExportCategory[]) {
                const id = categoryIdByName.get(category.name);
                if (id) categoryMap.set(category.id, id);
            }
            // Same database: IDs already match
            for (const category of currentCategories) {
                categoryMap.set(category.id, category.id);
            }

            // Children without own allowance (expense tags): match by name, add missing ones (parents only)
            const memberMap = new Map<string, string>();
            if (user?.role === 'PARENT') {
                const currentUsers: FamilyUser[] = (await api.get('/api/v1/users')).data;
                for (const member of (data.family || []) as FamilyUser[]) {
                    if (member.role !== 'CHILD' || member.has_allowance) continue;
                    const existing = currentUsers.find(u => u.username === member.username);
                    try {
                        const id = existing?.id ?? (await api.post('/api/v1/members', { username: member.username })).data.id;
                        memberMap.set(member.id, id);
                    } catch {
                        console.error('Failed to import family member', member.username);
                    }
                }
            }

            let imported = 0;
            let skipped = 0;

            // Import accounts
            const accountMap = new Map<string, string>();
            for (const account of (data.accounts || []) as ExportAccount[]) {
                try {
                    const res = await api.post('/api/v1/accounts', { name: account.name, type: account.type });
                    accountMap.set(account.id, res.data.id);
                } catch {
                    console.error('Failed to import account', account.name);
                }
            }

            // Import budgets
            for (const budget of (data.budgets || []) as ExportBudget[]) {
                const newCategoryId = categoryMap.get(budget.category_id);
                if (!newCategoryId) {
                    skipped++;
                    continue;
                }

                try {
                    await api.post('/api/v1/budgets', {
                        category_id: newCategoryId,
                        limit: budget.limit,
                        period: budget.period
                    });
                    imported++;
                } catch {
                    console.error('Failed to import budget');
                    skipped++;
                }
            }

            // Import transactions
            for (const transaction of (data.transactions || []) as ExportTransaction[]) {
                const newAccountId = accountMap.get(transaction.account_id);
                const newCategoryId = categoryMap.get(transaction.category_id);
                if (!newAccountId || !newCategoryId) {
                    skipped++;
                    continue;
                }

                try {
                    await api.post('/api/v1/transactions', {
                        account_id: newAccountId,
                        category_id: newCategoryId,
                        amount: transaction.amount,
                        description: transaction.description,
                        date: transaction.date,
                        // An unknown child just loses the tag; the expense itself is still imported
                        member_id: (transaction.member_id && memberMap.get(transaction.member_id)) || null
                    });
                    imported++;
                } catch {
                    console.error('Failed to import transaction');
                    skipped++;
                }
            }

            setStatus({
                kind: skipped > 0 ? 'error' : 'success',
                text: skipped > 0
                    ? `Imported ${imported} budgets and transactions; ${skipped} could not be imported (unknown account or category). Refresh the page to see them.`
                    : `Imported ${imported} budgets and transactions. Refresh the page to see them.`
            });
        } catch (error) {
            console.error('Failed to import data', error);
            setStatus({ kind: 'error', text: 'Failed to import data. Please check the file format.' });
        } finally {
            setImporting(false);
            // Allow importing the same file again
            input.value = '';
        }
    };

    const handlePrivacyToggle = async () => {
        setSavingPrivacy(true);
        try {
            await api.patch('/api/v1/me/privacy', {
                privacy_enabled: !privacyEnabled
            });
            setPrivacyEnabled(!privacyEnabled);
            await refreshUser();
            setStatus({ kind: 'success', text: `Privacy mode ${!privacyEnabled ? 'enabled' : 'disabled'}.` });
        } catch (error) {
            console.error('Failed to update privacy settings', error);
            setStatus({ kind: 'error', text: errorMessage(error, 'Failed to update privacy settings') });
        } finally {
            setSavingPrivacy(false);
        }
    };

    return (
        <div className="glass-card p-6">
            <h2 className="text-2xl font-bold mb-6">Data Management</h2>

            {status && (
                <div className={`mb-6 p-3 rounded-lg flex justify-between items-center border ${status.kind === 'success'
                    ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-300'
                    : 'bg-red-500/20 border-red-500/50 text-red-300'
                    }`}>
                    <span>{status.text}</span>
                    <button onClick={() => setStatus(null)} className="hover:text-white" aria-label="Dismiss message">✕</button>
                </div>
            )}

            {/* Export Section */}
            <div className="mb-8">
                <h3 className="text-lg font-semibold mb-4">Export Data</h3>
                <p className="text-slate-400 mb-4">
                    Download all your budget data including accounts, transactions, and budgets.
                </p>
                <div className="flex gap-4 items-center">
                    <select
                        value={exportFormat}
                        onChange={(e) => setExportFormat(e.target.value)}
                        className="p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
                    >
                        <option value="json">JSON Format</option>
                        <option value="csv">CSV Format</option>
                    </select>
                    <button onClick={handleExport} className="btn-primary">
                        📥 Export Data
                    </button>
                </div>
            </div>

            {/* Import Section */}
            <div className="mb-8">
                <h3 className="text-lg font-semibold mb-4">Import Data</h3>
                <p className="text-slate-400 mb-4">
                    Import budget data from a previously exported JSON file.
                </p>
                <div className="p-4 bg-yellow-500/10 border border-yellow-500/30 rounded-lg mb-4">
                    <p className="text-yellow-400 text-sm">
                        ⚠️ Warning: Importing will add new accounts and transactions. Duplicate data may be created if you import the same file multiple times.
                    </p>
                </div>
                <input
                    type="file"
                    accept=".json"
                    onChange={handleImport}
                    disabled={importing}
                    className="block w-full text-sm text-slate-400
            file:mr-4 file:py-2 file:px-4
            file:rounded file:border-0
            file:text-sm file:font-semibold
            file:bg-blue-500/20 file:text-blue-400
            hover:file:bg-blue-500/30
            file:cursor-pointer cursor-pointer"
                />
                {importing && (
                    <p className="mt-2 text-blue-400">Importing data...</p>
                )}
            </div>

            {/* Privacy Settings */}
            <div className="pt-8 border-t border-slate-700">
                <h3 className="text-lg font-semibold mb-4">Privacy & Security</h3>
                <div className="space-y-4">
                    <div className="p-4 bg-slate-800/30 rounded-lg">
                        <h4 className="font-semibold mb-2">Child Account Privacy</h4>
                        <p className="text-sm text-slate-400 mb-3">
                            {user?.role === 'CHILD'
                                ? 'When enabled, parents cannot view your transactions and balances.'
                                : 'Only a child with own allowance can turn this on, for their own data.'}
                        </p>
                        {user?.role === 'CHILD' && (
                            <label className="flex items-center gap-2 cursor-pointer">
                                <input
                                    type="checkbox"
                                    className="w-4 h-4"
                                    checked={privacyEnabled}
                                    onChange={handlePrivacyToggle}
                                    disabled={savingPrivacy}
                                />
                                <span>Enable privacy mode {savingPrivacy && '(Saving...)'}</span>
                            </label>
                        )}
                        {user?.role === 'PARENT' && (
                            <p className="text-sm text-slate-500 italic">
                                As a parent, you can view all child accounts that don't have privacy enabled.
                            </p>
                        )}
                    </div>

                    <div className="p-4 bg-slate-800/30 rounded-lg">
                        <h4 className="font-semibold mb-2">Data Retention</h4>
                        <p className="text-sm text-slate-400">
                            All data is stored locally in your database. You can export and backup your data at any time.
                        </p>
                    </div>

                    <div className="p-4 bg-blue-500/10 border border-blue-500/30 rounded-lg">
                        <h4 className="font-semibold mb-2 text-blue-400">🔒 Privacy Rules</h4>
                        <ul className="text-sm text-slate-400 space-y-1">
                            <li>• Parents share one household: they see each other's accounts and household budgets</li>
                            <li>• Parents can view children's own-allowance data (if privacy is off)</li>
                            <li>• Children can only view their own data</li>
                            <li>• Privacy mode hides all account and transaction data from parents</li>
                        </ul>
                    </div>
                </div>
            </div>
        </div>
    );
}
