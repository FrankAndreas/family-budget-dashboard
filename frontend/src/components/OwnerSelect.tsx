import { useTranslation } from 'react-i18next';
import { useAuth } from '../AuthContext';
import { useFamily } from '../useFamily';
import { accessTo } from '../family';
import { useSplits } from '../finance';

// Me, anyone whose money I may manage (a parent or child who shared with me, a younger child),
// or common with a split
export default function OwnerSelect({ value, onChange }: { value: string; onChange: (value: string) => void }) {
    const { t } = useTranslation();
    const { user } = useAuth();
    const { users, shares } = useFamily();
    const { splits } = useSplits();
    const others = users.filter(u => u.id !== user?.id && user && accessTo(user, u.id, users, shares) === 'EDIT');

    // The other parent or a child with own allowance only shows up once they let me manage their money
    const missing = users.some(u => u.id !== user?.id && !others.includes(u));

    return (
        <div>
            <select
                value={value}
                onChange={(e) => onChange(e.target.value)}
                className="w-full p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
                aria-label={t('owner.label')}
            >
                <option value={`owner:${user?.id}`}>{t('owner.mine')}</option>
                {others.map(u => <option key={u.id} value={`owner:${u.id}`}>{t('owner.someones', { name: u.username })}</option>)}
                {splits.map(split => <option key={split.id} value={`split:${split.id}`}>{t('owner.common', { name: split.name })}</option>)}
            </select>
            {missing && <p className="mt-1 text-xs text-slate-400">{t('owner.othersHint')}</p>}
        </div>
    );
}
