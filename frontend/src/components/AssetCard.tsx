import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { leaseEndsSoon, money, type Asset } from '../finance';
import { formatDate } from '../format';
import { openAttachment } from '../receipts';

interface Expense { id: string; amount: number; date: string; description: string | null }

interface Props {
    asset: Asset;
    owner: string;
    canChange: boolean;
    // The linked expenses, when its costs are open
    expenses: Expense[] | null;
    onToggleCosts: () => void;
    onEdit: () => void;
    onDelete: () => void;
    onArchive: (on: string) => void;
    onRestore: () => void;
}

// One investment: its age, when to replace it, what to set aside and what it cost so far
export default function AssetCard({ asset, owner, canChange, expenses, onToggleCosts, onEdit, onDelete, onArchive, onRestore }: Props) {
    const { t } = useTranslation();
    // The day it left, while asking for it
    const [leftOn, setLeftOn] = useState<string | null>(null);
    const used = Math.min(asset.age_years / asset.lifespan_years, 1);
    const today = new Date().toISOString().slice(0, 10);

    return (
        <div className="p-4 rounded-lg bg-slate-800/30 border border-slate-700">
            <div className="flex justify-between gap-2">
                <h3 className="font-semibold text-lg">{asset.name}</h3>
                {asset.planned && (
                    <span className="text-xs px-2 py-0.5 h-fit rounded-full bg-sky-500/20 text-sky-300">{t('investments.planned')}</span>
                )}
                {asset.is_due && (
                    <span className="text-xs px-2 py-0.5 h-fit rounded-full bg-amber-500/20 text-amber-300">{t('investments.due')}</span>
                )}
                {leaseEndsSoon(asset) && (
                    <span className="text-xs px-2 py-0.5 h-fit rounded-full bg-amber-500/20 text-amber-300">{t('investments.leaseEndsSoon')}</span>
                )}
            </div>
            <p className="text-xs text-slate-500">{owner}</p>
            <p className="text-sm mt-1">
                {t(`investments.${asset.kind === 'LEASE' ? 'downPaid' : 'boughtFor'}`, { amount: money(asset.price), date: formatDate(asset.purchase_date) })}
                {!asset.purchase && <span className="text-slate-400"> {t('investments.estimated')}</span>}
                {asset.purchase?.attachments.map(a => (
                    <button type="button" key={a.id} onClick={() => openAttachment(a)} title={a.filename}
                        aria-label={t('investments.openReceipt', { name: a.filename })} className="ml-2 text-sky-400 hover:underline">📎</button>
                ))}
            </p>
            <div className="mt-3 h-2 rounded bg-slate-700" role="img"
                aria-label={t('investments.age', { age: asset.age_years, lifespan: asset.lifespan_years })}>
                <div className={`h-2 rounded ${asset.is_due ? 'bg-amber-400' : 'bg-cyan-400'}`}
                    style={{ width: `${used * 100}%` }} />
            </div>
            <p className="text-sm text-slate-400 mt-1">
                {asset.planned
                    ? t('investments.plannedFor', { date: formatDate(asset.purchase_date) })
                    : t('investments.age', { age: asset.age_years, lifespan: asset.lifespan_years })}
                {' · '}
                {asset.archived_on
                    ? t('investments.archivedOn', { date: formatDate(asset.archived_on) })
                    : t('investments.replace', { year: new Date(asset.replacement_due).getFullYear() })}
            </p>
            {asset.lease_end && (
                <p className="text-sm text-slate-400">
                    {t(asset.monthly_rate > 0 ? 'investments.leaseUntil' : 'investments.leaseEnded', { date: formatDate(asset.lease_end) })}
                </p>
            )}
            {!asset.archived_on && (asset.monthly_rate > 0 ? (
                <p className="mt-2">
                    {t('investments.leaseLoad', { rate: money(asset.monthly_rate), saving: money(asset.monthly_set_aside), load: money(asset.monthly_load) })}
                </p>
            ) : (
                <p className="mt-2">
                    {t('investments.setAsideBefore')}<strong>{money(asset.monthly_set_aside)}</strong>{t('investments.setAsideAfter')}
                </p>
            ))}
            <div className="flex flex-wrap gap-3 mt-3 text-sm">
                <button onClick={onToggleCosts} className="text-slate-400 hover:text-white">
                    {expenses ? t('investments.hideCosts') : t('investments.costs')}
                </button>
                {canChange && (<>
                    {asset.archived_on ? (
                        <button onClick={onRestore} className="text-slate-400 hover:text-white"
                            aria-label={t('investments.restoreItem', { name: asset.name })}>{t('investments.restore')}</button>
                    ) : (<>
                        <button onClick={onEdit} className="text-slate-400 hover:text-white">{t('common.edit')}</button>
                        <button onClick={() => setLeftOn(leftOn ? null : today)} className="text-slate-400 hover:text-white"
                            aria-label={t('investments.archiveItem', { name: asset.name })}>{t('investments.archive')}</button>
                    </>)}
                    <button onClick={onDelete} className="text-slate-400 hover:text-red-400">{t('common.delete')}</button>
                </>)}
            </div>
            {leftOn && !asset.archived_on && (
                <form className="mt-3 flex flex-wrap items-end gap-2 text-sm"
                    onSubmit={(e) => { e.preventDefault(); onArchive(leftOn); setLeftOn(null); }}>
                    <label className="text-slate-400">{t('investments.leftOn')}
                        <input type="date" value={leftOn} min={asset.purchase_date} max={today} required
                            onChange={(e) => setLeftOn(e.target.value)}
                            className="block p-2 rounded bg-slate-800/50 border border-slate-600 text-white" />
                    </label>
                    <button type="submit" className="btn-primary">{t('investments.archive')}</button>
                    <button type="button" onClick={() => setLeftOn(null)} className="px-2 text-slate-400 hover:text-white">{t('common.cancel')}</button>
                </form>
            )}
            {expenses && (
                <div className="mt-3 pt-3 border-t border-slate-700 text-sm space-y-1">
                    {expenses.map(e => (
                        <p key={e.id} className="text-slate-400">
                            {formatDate(e.date)} · {e.description || t('common.noDescription')} · {money(Math.abs(e.amount))}
                        </p>
                    ))}
                    <p className="font-semibold">
                        {t('investments.total', { total: money(asset.total_cost), perYear: money(asset.cost_per_year) })}
                    </p>
                    {asset.notes && <p className="text-slate-400">📝 {asset.notes}</p>}
                </div>
            )}
        </div>
    );
}
