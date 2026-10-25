import { useTranslation } from 'react-i18next';
import type { Asset } from '../finance';

interface Props {
    assets: Asset[];
    assetId: string;
    purchase: boolean;
    onChange: (assetId: string, purchase: boolean) => void;
    className: string;
}

// "For item" on a booking, and whether the booking bought it (then its receipt is the investment's receipt)
export default function AssetLink({ assets, assetId, purchase, onChange, className }: Props) {
    const { t } = useTranslation();
    return (
        <div className="flex flex-wrap items-center gap-x-3">
            <select
                value={assetId}
                onChange={(e) => onChange(e.target.value, false)}
                className={className}
                aria-label={t('transactions.forItem')}
            >
                <option value="">{t('transactions.forNoItem')}</option>
                {/* An archived item only while this booking is linked to it */}
                {assets.filter(asset => !asset.archived_on || asset.id === assetId).map(asset => (
                    <option key={asset.id} value={asset.id}>{t('transactions.forItemName', { name: asset.name })}</option>
                ))}
            </select>
            {assetId && (
                <label className="text-sm text-slate-300 flex items-center gap-2 mb-2">
                    <input type="checkbox" checked={purchase} onChange={(e) => onChange(assetId, e.target.checked)} />
                    {t('transactions.isPurchase')}
                </label>
            )}
        </div>
    );
}
