import { useAuth } from '../../AuthContext';
import { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import api, { errorMessage, fetchAllTransactions } from '../../api';
import BudgetManager from '../../components/BudgetManager';
import Analytics from '../../components/Analytics';
import DataManager from '../../components/DataManager';
import FamilyManager from '../../components/FamilyManager';
import CategoryManager from '../../components/CategoryManager';
import TagManager from '../../components/TagManager';
import ShareSettings from '../../components/ShareSettings';
import Logins from '../../components/Logins';
import CommonBudget from '../../components/CommonBudget';
import Investments from '../../components/Investments';
import YearlyBills from '../../components/YearlyBills';
import MonthCheck from '../../components/MonthCheck';
import Wishes from '../../components/Wishes';
import { useAssets, useSplits } from '../../finance';
import type { Account, Category, Transaction } from '../../accounts';
import AccountCards from '../../components/AccountCards';
import Transactions from '../../components/Transactions';
import Inbox from '../../components/Inbox';
import { useReceiptReading } from '../../receipts';
import { useFamily } from '../../useFamily';
import { accessTo, canWrite, dependents } from '../../family';

export default function Dashboard() {
    const { t } = useTranslation();
    const { user, logout } = useAuth();
    const { users, shares, reload: reloadFamily } = useFamily();
    const { splits, reload: reloadSplits } = useSplits();
    const { assets, reload: reloadAssets } = useAssets();
    const [activeTab, setActiveTab] = useState('overview');
    // Photographing a pile of receipts into the inbox (receipt scan)
    const [scanning, setScanning] = useState(false);
    // On a phone the tab row doesn't fit: a fade with an arrow at its end shows there are more tabs
    const tabRow = useRef<HTMLDivElement>(null);
    const [moreTabs, setMoreTabs] = useState(false);
    const updateMoreTabs = () => {
        const row = tabRow.current;
        setMoreTabs(!!row && row.scrollLeft + row.clientWidth < row.scrollWidth - 4);
    };
    useEffect(() => {
        updateMoreTabs();
        window.addEventListener('resize', updateMoreTabs);
        return () => window.removeEventListener('resize', updateMoreTabs);
    }, [user?.role]);
    const [accounts, setAccounts] = useState<Account[]>([]);
    const [categories, setCategories] = useState<Category[]>([]);
    const [selectedAccount, setSelectedAccount] = useState<string | null>(null);
    const [transactions, setTransactions] = useState<Transaction[]>([]);
    const [error, setError] = useState('');
    // Bumped after any change to load accounts and the selected account's transactions again
    const [dataVersion, setDataVersion] = useState(0);
    const refresh = () => setDataVersion(v => v + 1);
    const aiEnabled = useReceiptReading();

    useEffect(() => {
        api.get('/api/v1/categories')
            .then(response => setCategories(response.data))
            .catch(error => {
                console.error('Failed to load categories', error);
                setError(errorMessage(error, t('dashboard.loadCategoriesFailed')));
            });
    }, [t]);

    useEffect(() => {
        api.get('/api/v1/accounts')
            .then(response => {
                const loaded: Account[] = response.data;
                setAccounts(loaded);
                // Keep the selection if that account still exists, otherwise pick the first one
                setSelectedAccount(prev =>
                    prev && loaded.some(a => a.id === prev) ? prev : loaded[0]?.id ?? null
                );
            })
            .catch(error => {
                console.error('Failed to load accounts', error);
                setError(errorMessage(error, t('dashboard.loadAccountsFailed')));
            });
    }, [dataVersion, t]);

    useEffect(() => {
        if (!selectedAccount) return;
        fetchAllTransactions<Transaction>(selectedAccount)
            .then(setTransactions)
            .catch(error => {
                console.error('Failed to load transactions', error);
                setError(errorMessage(error, t('dashboard.loadTransactionsFailed')));
            });
    }, [selectedAccount, dataVersion, t]);

    const ownerOf = (account: Account) => users.find(u => u.id === account.user_id);
    const canEdit = (account: Account) => !!user && canWrite(accessTo(user, account.user_id, users, shares));
    const selectedAccountObj = accounts.find(a => a.id === selectedAccount);
    // A deleted account's transactions stay loaded until another one is selected; don't show them
    const shownTransactions = selectedAccountObj ? transactions : [];
    const isParent = user?.role === 'PARENT';

    const tabs = [
        'overview', 'budgets', ...(isParent ? ['common', 'investments', 'bills'] as const : []), 'wishes', 'analytics', 'settings',
    ] as const;

    return (
        <div className="min-h-screen p-3 sm:p-6">
            {/* Header */}
            <div className="glass-card p-4 sm:p-6 mb-4 sm:mb-6">
                <div className="flex justify-between items-center gap-3">
                    <div className="min-w-0">
                        <h1 className="text-2xl sm:text-3xl font-bold bg-gradient-to-r from-cyan-400 to-fuchsia-400 bg-clip-text text-transparent">
                            {t('common.appName')}
                        </h1>
                        <p className="text-slate-400 mt-1">
                            {t('dashboard.welcome', { name: user?.username, role: user ? t(`common.roles.${user.role}`) : '' })}
                        </p>
                    </div>
                    <button onClick={logout} className="btn-primary">
                        {t('dashboard.logout')}
                    </button>
                </div>
            </div>

            {error && (
                <div className="mb-6 p-4 bg-red-500/20 border border-red-500/50 rounded-lg text-red-300 flex justify-between items-center">
                    <span>{error}</span>
                    <button onClick={() => setError('')} className="text-red-300 hover:text-white" aria-label={t('common.dismissError')}>✕</button>
                </div>
            )}

            {/* Tab Navigation */}
            <div className="glass-card p-2 mb-4 sm:mb-6 relative">
                <div ref={tabRow} onScroll={updateMoreTabs} className="flex gap-2 overflow-x-auto">
                    {tabs.map(tab => (
                        <button
                            key={tab}
                            onClick={event => {
                                event.currentTarget.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' });
                                setActiveTab(tab);
                                // Other tabs may have changed the family, splits or investments the forms here offer
                                reloadFamily();
                                reloadSplits();
                                reloadAssets();
                            }}
                            className={`flex-1 whitespace-nowrap py-2 px-3 sm:py-3 sm:px-4 rounded-lg font-semibold transition-all ${activeTab === tab
                                ? 'bg-blue-500/20 text-blue-400 border-2 border-blue-400'
                                : 'text-slate-400 hover:bg-slate-800/30'
                                }`}
                        >
                            {t(`dashboard.tabs.${tab}`)}
                        </button>
                    ))}
                </div>
                {moreTabs && (
                    <button type="button" aria-label={t('dashboard.moreTabs')}
                        onClick={() => tabRow.current?.scrollBy({ left: tabRow.current.clientWidth * 0.8, behavior: 'smooth' })}
                        className="absolute right-0 inset-y-0 w-12 rounded-r-2xl flex items-center justify-end pr-2 text-2xl text-slate-300 bg-gradient-to-l from-slate-900 via-slate-900/80 to-transparent">
                        ›
                    </button>
                )}
            </div>

            {/* Tab Content */}
            {activeTab === 'overview' && (
                <div className="space-y-6">
                    {/* Receipt mails forwarded by the family, for parents to release (issue #57) */}
                    {isParent && (
                        <Inbox
                            accounts={accounts.filter(canEdit)}
                            categories={categories.filter(c => c.type === 'EXPENSE')}
                            people={users.filter(u => u.is_active !== false)}
                            aiEnabled={aiEnabled}
                            version={dataVersion}
                            onBooked={refresh}
                            scanning={scanning}
                            onScan={() => setScanning(true)}
                            onScanDone={() => { setScanning(false); refresh(); }}
                        />
                    )}
                    <AccountCards
                        accounts={accounts}
                        transactionCount={shownTransactions.length}
                        selectedAccount={selectedAccount}
                        onSelect={setSelectedAccount}
                        ownerOf={ownerOf}
                        canEdit={canEdit}
                        onChanged={refresh}
                        onDeleted={(accountId) => {
                            // Don't load the deleted account's transactions; the next account gets selected
                            if (accountId === selectedAccount) setSelectedAccount(null);
                            refresh();
                        }}
                        onError={setError}
                    />

                    {/* Clearing accounts (Migros, ...) should end every month at 0 */}
                    <MonthCheck
                        accounts={accounts.filter(a => a.type === 'CLEARING')}
                        canBook={canEdit}
                        version={dataVersion}
                        onBooked={refresh}
                    />

                    {selectedAccountObj && (
                        <Transactions
                            account={selectedAccountObj}
                            transactions={shownTransactions}
                            categories={categories}
                            canEdit={canEdit(selectedAccountObj)}
                            ownerName={ownerOf(selectedAccountObj)?.username}
                            isParentAccount={ownerOf(selectedAccountObj)?.role === 'PARENT'}
                            isParent={isParent}
                            children={dependents(users)}
                            people={users.filter(u => u.is_active !== false)}
                            splits={splits}
                            assets={assets}
                            onChanged={refresh}
                            onError={setError}
                        />
                    )}
                </div>
            )}

            {activeTab === 'budgets' && <BudgetManager />}
            {activeTab === 'common' && <CommonBudget />}
            {activeTab === 'investments' && <Investments />}
            {activeTab === 'bills' && <YearlyBills />}
            {activeTab === 'wishes' && <Wishes />}
            {activeTab === 'analytics' && <Analytics />}
            {activeTab === 'settings' && (
                <div className="space-y-6">
                    {user?.role === 'PARENT' && <FamilyManager />}
                    {user?.role === 'PARENT' && <CategoryManager />}
                    {user?.role === 'PARENT' && <TagManager />}
                    <ShareSettings />
                    <Logins />
                    <DataManager onDataChanged={refresh} />
                </div>
            )}
        </div>
    );
}
