import { useTranslation } from 'react-i18next';
import ImportRules from './ImportRules';
import ArticleRules from './ArticleRules';
import Section from './Section';

// Parents: the rules that give imported bookings (bank statements, files) and Migros receipt articles their
// category. They used to sit under Data Management; they belong with the categories they choose
export default function RuleSettings({ version }: { version: number }) {
    const { t } = useTranslation();
    return (
        <Section id="rules" title={t('ruleSettings.title')}>
            <ImportRules version={version} />
            <ArticleRules version={version} />
        </Section>
    );
}
