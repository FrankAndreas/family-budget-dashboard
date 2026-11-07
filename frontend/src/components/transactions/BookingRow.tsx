import { useTranslation } from 'react-i18next';
import type { BankRow, Transaction } from '../../accounts';
import { money } from '../../finance';
import { formatDate } from '../../format';
import { openAttachment } from '../../receipts';
import { badges, rowCategory, type Lookups } from './bookingList';

export interface RowAction { key: string; icon: string; name: string; label: string; danger?: boolean; run: () => void }

interface Props {
    transaction: Transaction;
    look: Lookups;
    canEdit: boolean;
    // What can be done with it: icons on a desktop, named buttons behind "⋯" on a phone
    actions: RowAction[];
    menuOpen: boolean;
    onMenu: (open: boolean) => void;
    // Its items, receipt files, bank lines and reconciliation shown
    expanded: boolean;
    onToggleExpanded: () => void;
    // Bank lines no booking is linked to yet, to link to this one
    unlinked: BankRow[];
    onLinkRow: (rowId: string) => void;
    onUnlinkRow: (rowId: string) => void;
    onFlag: (flag: 'receipt_expected' | 'difference_accepted', value: boolean) => void;
}

const badge = 'ml-2 inline-block whitespace-nowrap text-xs font-normal px-2 py-0.5 rounded-full';

// One booking in the list
export default function BookingRow({
    transaction, look, canEdit, actions, menuOpen, onMenu, expanded, onToggleExpanded, unlinked, onLinkRow, onUnlinkRow, onFlag
}: Props) {
    const { t } = useTranslation();
    const memberName = look.memberName(transaction.member_id);
    const assetName = look.assetName(transaction.asset_id);
    const category = rowCategory(transaction, look, t);
    return (
        <div className="px-3 py-2 sm:p-3 bg-slate-800/30 rounded-lg">
            <div className="flex justify-between items-center gap-2">
                <div className="min-w-0 flex-1">
                    <p className="font-semibold break-words">
                        {transaction.description || t('transactions.noDescription')}
                        {memberName && (
                            <span className={`${badge} bg-indigo-500/20 text-indigo-300`}>
                                {t('transactions.forBadge', { name: memberName })}
                            </span>
                        )}
                        {assetName && <span className={`${badge} bg-amber-500/20 text-amber-300`}>{assetName}</span>}
                        {look.isExpense(transaction.category_id) && transaction.amount > 0 && (
                            <span className={`${badge} bg-emerald-500/20 text-emerald-300`}>{t('transactions.refundBadge')}</span>
                        )}
                        {(transaction.split_id || transaction.split_shares) && (
                            <span className={`${badge} bg-cyan-500/20 text-cyan-300`}>{t('transactions.sharedBadge')}</span>
                        )}
                        {badges(transaction, t).map(b => (
                            <span key={b.text} className={`${badge} ${b.warn ? 'bg-amber-500/20 text-amber-300' : 'bg-slate-500/20 text-slate-300'}`}>
                                {b.text}
                            </span>
                        ))}
                    </p>
                </div>
                <div className="flex items-center gap-1 sm:gap-2 shrink-0">
                    <p className={`text-lg sm:text-xl font-bold whitespace-nowrap ${transaction.amount >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {transaction.amount >= 0 ? '+ ' : ''}{money(transaction.amount)}
                    </p>
                    {/* Desktop: the actions as icons */}
                    <div className="hidden sm:flex items-center gap-1">
                        {actions.map(action => (
                            <button key={action.key} onClick={action.run} title={action.label} aria-label={action.label}
                                className={`w-10 h-10 flex items-center justify-center rounded-lg text-slate-500 hover:bg-slate-700/40 transition-colors ${action.danger ? 'ml-2 hover:text-red-400' : 'hover:text-blue-400'}`}>
                                {action.icon}
                            </button>
                        ))}
                    </div>
                    {/* Phone: one button keeps the row on one line; the actions open below it with their names */}
                    {actions.length > 0 && (
                        <button onClick={() => onMenu(!menuOpen)}
                            aria-label={t('transactions.actions')} aria-expanded={menuOpen}
                            className="sm:hidden w-10 h-10 flex items-center justify-center rounded-lg text-xl text-slate-400 hover:bg-slate-700/40">
                            ⋯
                        </button>
                    )}
                </div>
            </div>
            {/* Under the description and amount, across the whole row: on a phone it has room there */}
            <p className="text-sm text-slate-400 -mt-1">
                {formatDate(transaction.date)}
                {category && <span className="ml-2">· {category}</span>}
                {(transaction.items?.length || transaction.attachments?.length || transaction.bank_rows?.length || transaction.state) ? (
                    <button onClick={onToggleExpanded} className="ml-3 text-sky-400 hover:underline">
                        {transaction.items?.length ? t('receipt.items', { count: transaction.items.length }) : ''}
                        {transaction.attachments?.length ? ` ${t('receipt.attachmentsCount', { count: transaction.attachments.length })}` : ''}
                        {transaction.bank_rows?.length ? ` ${t('reconcile.bankLines', { count: transaction.bank_rows.length })}` : ''}
                        {!transaction.items?.length && !transaction.attachments?.length && !transaction.bank_rows?.length ? t('reconcile.more') : ''}
                    </button>
                ) : null}
            </p>
            {menuOpen && (
                <div className="sm:hidden mt-2 flex flex-wrap gap-2">
                    {actions.map(action => (
                        <button key={action.key} onClick={() => { onMenu(false); action.run(); }} aria-label={action.label}
                            className={`h-10 px-3 rounded-lg border text-sm ${action.danger ? 'border-red-500/40 text-red-300' : 'border-slate-600 text-slate-200'}`}>
                            {action.icon} {action.name}
                        </button>
                    ))}
                </div>
            )}
            {expanded && (
                <div className="mt-2 pt-2 border-t border-slate-700 text-sm space-y-1">
                    {transaction.items?.map(item => (
                        <div key={item.id} className="flex flex-wrap items-center gap-x-3 gap-y-1">
                            <span className="flex-1 min-w-32">{item.name}</span>
                            <span className="text-slate-400">{look.categoryName(item.category_id)}</span>
                            {item.tag_ids.map(id => (
                                <span key={id} className="text-xs px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-200">{look.tagLabel(id)}</span>
                            ))}
                            {look.personName(item.person_id) && (
                                <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300">{look.personName(item.person_id)}</span>
                            )}
                            <span className="w-24 text-right">{money(item.amount)}</span>
                        </div>
                    ))}
                    {transaction.attachments?.map(a => (
                        <button key={a.id} onClick={() => openAttachment(a)} className="block text-sky-400 hover:underline">
                            📎 {a.filename}
                        </button>
                    ))}
                    {transaction.bank_rows?.map(row => (
                        <div key={row.id} className="flex flex-wrap items-center gap-x-3 text-slate-300">
                            <span className="flex-1 min-w-32">🏦 {formatDate(row.booked_on)} · {row.text}</span>
                            <span className="w-24 text-right">{money(row.amount)}</span>
                            {canEdit && (
                                <button onClick={() => onUnlinkRow(row.id)} className="text-slate-500 hover:text-red-400">
                                    {t('reconcile.unlink')}
                                </button>
                            )}
                        </div>
                    ))}
                    {canEdit && transaction.state && (
                        <div className="flex flex-wrap items-center gap-3 pt-1">
                            {unlinked.length > 0 && (
                                <select value="" onChange={e => e.target.value && onLinkRow(e.target.value)}
                                    aria-label={t('reconcile.linkLine')}
                                    className="p-1 rounded bg-slate-800/50 border border-slate-600 text-white">
                                    <option value="">{t('reconcile.linkLine')}</option>
                                    {unlinked.map(row => (
                                        <option key={row.id} value={row.id}>{formatDate(row.booked_on)} · {row.text} · {money(row.amount)}</option>
                                    ))}
                                </select>
                            )}
                            <label className="flex items-center gap-1">
                                <input type="checkbox" checked={!!transaction.receipt_expected}
                                    onChange={e => onFlag('receipt_expected', e.target.checked)} />
                                {t('reconcile.receiptExpected')}
                            </label>
                            {transaction.state.differs && (
                                <button onClick={() => onFlag('difference_accepted', true)} className="text-sky-400 hover:underline">
                                    {t('reconcile.acceptDifference')}
                                </button>
                            )}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
