import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import api, { errorMessage, fetchAllTransactions } from '../api';
import { useAuth } from '../AuthContext';
import type { FamilyUser } from '../family';
import { useFamily } from '../useFamily';
import { downloadBlob } from '../download';
import { localDay } from '../format';
import ImportTransactions from './ImportTransactions';
import Section from './Section';

interface ExportAccount {
    id: string;
    user_id: string;
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

// The same booking in a backup and in the database: account, category, day and time, amount and text
const bookingKey = (accountId: string, categoryId: string, b: { date: string; amount: number; description?: string | null }) =>
    [accountId, categoryId, new Date(b.date).toISOString(), Math.round(b.amount * 100), (b.description ?? '').trim()].join('|');

interface ExportTransaction {
    account_id: string;
    category_id: string;
    amount: number;
    description?: string | null;
    date: string;
    member_id?: string | null;
    reference?: string | null;
    account_name?: string;
}

interface Status {
    kind: 'success' | 'error';
    text: string;
}

const today = () => localDay();

// onDataChanged: an import or restore added accounts and transactions the rest of the app should reload
export default function DataManager({ onDataChanged }: { onDataChanged?: () => void }) {
    const { t } = useTranslation();
    const { user, refreshUser } = useAuth();
    // Bumped after an import, which may have saved new import rules
    const { users } = useFamily();
    // Only the rules that apply to this family: another parent, children with their own money
    const otherParent = users.some(u => u.role === 'PARENT' && u.id !== user?.id && u.is_active !== false);
    const allowanceChildren = users.some(u => u.role === 'CHILD' && u.has_allowance && u.is_active !== false);
    const privacyRules = [
        ...(otherParent ? ['parents', 'common'] as const : []),
        ...(allowanceChildren || user?.role === 'CHILD' ? ['children', 'own', 'privacy'] as const : []),
    ];
    const showChildPrivacy = user?.role === 'CHILD' || allowanceChildren;
    const [importing, setImporting] = useState(false);
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

            // Only your own accounts: a restore creates them as yours, and others' accounts (even shared) aren't yours
            const accounts = (accountsRes.data as ExportAccount[]).filter(a => a.user_id === user?.id);
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

            const exportData = {
                exported_at: new Date().toISOString(),
                accounts,
                categories,
                budgets: budgetsRes.data,
                transactions: allTransactions,
                // Needed to restore which child a household expense was for
                family: family.map(({ id, username, role, has_allowance }) => ({ id, username, role, has_allowance }))
            };
            downloadBlob(new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' }), `budget-export-${today()}.json`);
            setStatus({ kind: 'success', text: t('data.exported', { count: allTransactions.length }) });
        } catch (error) {
            console.error('Failed to export data', error);
            setStatus({ kind: 'error', text: errorMessage(error, t('data.exportFailed')) });
        }
    };

    const handleAnalysisExport = async () => {
        try {
            const res = await api.get('/api/v1/export/analysis.zip', { responseType: 'blob' });
            downloadBlob(res.data, `budget-analysis-${today()}.zip`);
            setStatus({ kind: 'success', text: t('data.exportedAnalysis') });
        } catch (error) {
            console.error('Failed to export data for analysis', error);
            setStatus({ kind: 'error', text: errorMessage(error, t('data.exportFailed')) });
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
            // Already there (restored before, or never lost): not created a second time
            let existing = 0;

            // Accounts: your own one with the same name and type is used again, otherwise a new one
            const ownAccounts = ((await api.get('/api/v1/accounts')).data as ExportAccount[]).filter(a => a.user_id === user?.id);
            const accountMap = new Map<string, string>();
            // What each reused account already holds, per booking (see bookingKey), counted: two equal coffees stay two
            const alreadyBooked = new Map<string, number>();
            for (const account of (data.accounts || []) as ExportAccount[]) {
                const found = ownAccounts.find(a => a.id === account.id)
                    ?? ownAccounts.find(a => a.name === account.name && a.type === account.type && ![...accountMap.values()].includes(a.id));
                try {
                    if (found) {
                        accountMap.set(account.id, found.id);
                        for (const booking of await fetchAllTransactions<ExportTransaction>(found.id)) {
                            const key = bookingKey(found.id, booking.category_id, booking);
                            alreadyBooked.set(key, (alreadyBooked.get(key) ?? 0) + 1);
                        }
                    } else {
                        const res = await api.post('/api/v1/accounts', { name: account.name, type: account.type });
                        accountMap.set(account.id, res.data.id);
                    }
                } catch {
                    console.error('Failed to import account', account.name);
                }
            }

            // Budgets: one per category and period
            const ownBudgets: ExportBudget[] = (await api.get('/api/v1/budgets')).data;
            const budgetKeys = new Set(ownBudgets.map(b => `${b.category_id}|${b.period}`));
            for (const budget of (data.budgets || []) as ExportBudget[]) {
                const newCategoryId = categoryMap.get(budget.category_id);
                if (!newCategoryId) {
                    skipped++;
                    continue;
                }
                if (budgetKeys.has(`${newCategoryId}|${budget.period}`)) {
                    existing++;
                    continue;
                }
                budgetKeys.add(`${newCategoryId}|${budget.period}`);

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
                const key = bookingKey(newAccountId, newCategoryId, transaction);
                const left = alreadyBooked.get(key) ?? 0;
                if (left > 0) {
                    alreadyBooked.set(key, left - 1);
                    existing++;
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
                        member_id: (transaction.member_id && memberMap.get(transaction.member_id)) || null,
                        // Money back in an expense category stays a refund (the server ignores it for income)
                        refund: transaction.amount > 0,
                        reference: transaction.reference ?? null
                    });
                    imported++;
                } catch {
                    console.error('Failed to import transaction');
                    skipped++;
                }
            }

            onDataChanged?.();
            const text = [
                skipped > 0 ? t('data.restoredSkipped', { count: imported, skipped }) : t('data.restored', { count: imported }),
                ...(existing > 0 ? [t('data.restoredExisting', { count: existing })] : []),
            ].join(' ');
            setStatus({ kind: skipped > 0 ? 'error' : 'success', text });
        } catch (error) {
            console.error('Failed to import data', error);
            setStatus({ kind: 'error', text: t('data.restoreFailed') });
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
            setStatus({ kind: 'success', text: !privacyEnabled ? t('data.privacyEnabled') : t('data.privacyDisabled') });
        } catch (error) {
            console.error('Failed to update privacy settings', error);
            setStatus({ kind: 'error', text: errorMessage(error, t('data.privacyFailed')) });
        } finally {
            setSavingPrivacy(false);
        }
    };

    return (
        <Section id="data" title={t('data.title')}>

            {status && (
                <div className={`mb-6 p-3 rounded-lg flex justify-between items-center border ${status.kind === 'success'
                    ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-300'
                    : 'bg-red-500/20 border-red-500/50 text-red-300'
                    }`}>
                    <span>{status.text}</span>
                    <button onClick={() => setStatus(null)} className="hover:text-white" aria-label={t('data.dismiss')}>✕</button>
                </div>
            )}

            {/* Export Section */}
            <div className="mb-8">
                <h3 className="text-lg font-semibold mb-4">{t('data.exportTitle')}</h3>
                <p className="text-slate-400 mb-4">
                    <strong>{t('data.forAnalysis')}</strong>{t('data.forAnalysisText')}
                    <br />
                    <strong>{t('data.backup')}</strong>{t('data.backupText')}
                </p>
                <div className="flex flex-wrap gap-4 items-center">
                    <button onClick={handleAnalysisExport} className="btn-primary">
                        {t('data.exportAnalysis')}
                    </button>
                    <button onClick={handleExport} className="btn-primary">
                        {t('data.exportBackup')}
                    </button>
                </div>
            </div>

            {/* The rules it learns are in their own Settings section (reloaded through onDataChanged) */}
            <ImportTransactions onImported={() => onDataChanged?.()} />

            {/* Restore Section */}
            <div className="mb-8">
                <h3 className="text-lg font-semibold mb-4">{t('data.restoreTitle')}</h3>
                <p className="text-slate-400 mb-4">{t('data.restoreIntro')}</p>
                <p className="text-sm text-slate-400 mb-4">{t('data.restoreAgain')}</p>
                <input
                    type="file"
                    accept=".json"
                    aria-label={t('data.restoreFile')}
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
                    <p className="mt-2 text-blue-400">{t('data.importing')}</p>
                )}
            </div>

            {/* Privacy: only what applies to this family (nothing for a parent on their own) */}
            {(showChildPrivacy || privacyRules.length > 0) && (
                <div className="pt-8 border-t border-slate-700">
                    <h3 className="text-lg font-semibold mb-4">{t('data.privacyTitle')}</h3>
                    <div className="space-y-4">
                        {showChildPrivacy && (
                            <div className="p-4 bg-slate-800/30 rounded-lg">
                                <h4 className="font-semibold mb-2">{t('data.childPrivacy')}</h4>
                                <p className="text-sm text-slate-400 mb-3">
                                    {user?.role === 'CHILD' ? t('data.childPrivacyChild') : t('data.childPrivacyParent')}
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
                                        <span>{t('data.enablePrivacy')}{savingPrivacy && t('data.saving')}</span>
                                    </label>
                                )}
                                {user?.role === 'PARENT' && (
                                    <p className="text-sm text-slate-500 italic">{t('data.parentPrivacy')}</p>
                                )}
                            </div>
                        )}
                        {privacyRules.length > 0 && (
                            <div className="p-4 bg-blue-500/10 border border-blue-500/30 rounded-lg">
                                <h4 className="font-semibold mb-2 text-blue-400">{t('data.rulesTitle')}</h4>
                                <ul className="text-sm text-slate-400 space-y-1">
                                    {privacyRules.map(rule => <li key={rule}>• {t(`data.rules.${rule}`)}</li>)}
                                </ul>
                            </div>
                        )}
                    </div>
                </div>
            )}
        </Section>
    );
}
