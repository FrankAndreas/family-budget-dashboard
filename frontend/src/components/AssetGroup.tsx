import { useTranslation } from 'react-i18next';
import { assetTotals, money, type Asset } from '../finance';
import { useRememberedOpen } from '../useRememberedOpen';

interface Props {
    // Remembers whether it is open, in this browser
    id: string;
    title: string;
    assets: Asset[];
    children: React.ReactNode;
}

// The investments with one tag: a folding group whose header says what they cost together
export default function AssetGroup({ id, title, assets, children }: Props) {
    const { t } = useTranslation();
    const { open, toggle } = useRememberedOpen(`investments.group.${id}`);
    const sums = assetTotals(assets);
    return (
        <details open={open} onToggle={toggle} className="group rounded-lg border border-slate-700">
            <summary className="p-3 cursor-pointer list-none flex flex-wrap items-center gap-x-3 gap-y-1 [&::-webkit-details-marker]:hidden">
                <span aria-hidden="true" className="text-slate-400 transition-transform group-open:rotate-90">›</span>
                <h3 className="font-semibold">{title}</h3>
                <span className="text-sm text-slate-400">{t('investments.count', { count: assets.length })}</span>
                <span className="text-sm"><strong>{t('investments.perMonth', { amount: money(sums.monthly) })}</strong></span>
                <span className="text-sm text-slate-400">{t('investments.soFar', { amount: money(sums.total) })}</span>
                {sums.dueSoon && (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300">{t('investments.dueSoon')}</span>
                )}
            </summary>
            <div className="px-3 pb-3">
                <p className="text-sm text-slate-400 mb-3">
                    {t('investments.groupSummary', { price: money(sums.price), followUps: money(sums.followUps), perYear: money(sums.perYear) })}
                    {sums.next && <>{' · '}{t('investments.nextReplacement', { year: new Date(sums.next.replacement_due).getFullYear(), name: sums.next.name })}</>}
                </p>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">{children}</div>
            </div>
        </details>
    );
}

// The archived investments: folded at first, also on a wide screen
export function ArchivedGroup({ count, children }: { count: number; children: React.ReactNode }) {
    const { t } = useTranslation();
    const { open, toggle } = useRememberedOpen('investments.archived', false);
    return (
        <details open={open} onToggle={toggle} className="group rounded-lg border border-slate-700/60">
            <summary className="p-3 cursor-pointer list-none flex items-center gap-3 text-slate-400 [&::-webkit-details-marker]:hidden">
                <span aria-hidden="true" className="transition-transform group-open:rotate-90">›</span>
                <h3 className="font-semibold">{t('investments.archived', { count })}</h3>
            </summary>
            <div className="px-3 pb-3 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 opacity-80">{children}</div>
        </details>
    );
}
