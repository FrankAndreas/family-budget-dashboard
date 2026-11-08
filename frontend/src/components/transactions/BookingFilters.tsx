import { useTranslation } from 'react-i18next';
import type { Category } from '../../accounts';

interface Props {
    query: string;
    categoryFilter: string;
    // The categories of the bookings in the list
    categories: Category[];
    categoryLabel: (id: string) => string;
    onQuery: (query: string) => void;
    onCategory: (categoryId: string) => void;
}

// Finding a booking: words, and one category
export default function BookingFilters({ query, categoryFilter, categories, categoryLabel, onQuery, onCategory }: Props) {
    const { t } = useTranslation();
    const filtering = !!query.trim() || !!categoryFilter;
    return (
        <div className="flex flex-wrap gap-2 mb-4">
            <input type="search" value={query} onChange={e => onQuery(e.target.value)}
                aria-label={t('transactions.search')} placeholder={t('transactions.search')}
                className="flex-1 min-w-48 p-2 rounded bg-slate-800/50 border border-slate-500 text-white" />
            <select value={categoryFilter} onChange={e => onCategory(e.target.value)}
                aria-label={t('transactions.filterCategory')}
                className="p-2 rounded bg-slate-800/50 border border-slate-500 text-white">
                <option value="">{t('transactions.allCategories')}</option>
                {categories.map(c => <option key={c.id} value={c.id}>{categoryLabel(c.id)}</option>)}
            </select>
            {filtering && (
                <button type="button" onClick={() => { onQuery(''); onCategory(''); }}
                    className="px-3 text-sm text-slate-400 hover:text-white">
                    {t('transactions.clearFilter')}
                </button>
            )}
        </div>
    );
}
