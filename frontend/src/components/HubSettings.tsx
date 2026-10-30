import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api';
import Section from './Section';

// Settings → the family hub: PIN, language, logging out on every device and who belongs to the family live there now
export default function HubSettings() {
    const { t } = useTranslation();
    const [hubUrl, setHubUrl] = useState<string | null>(null);

    useEffect(() => {
        api.get<{ login_url: string }>('/api/v1/hub').then(res => setHubUrl(res.data.login_url)).catch(() => setHubUrl(null));
    }, []);

    return (
        <Section id="hub" title={t('hubLogin.settingsTitle')}>
            <p className="text-slate-400 text-sm mb-3">{t('hubLogin.settingsIntro')}</p>
            {hubUrl && <a href={hubUrl} className="btn-primary inline-block">{t('hubLogin.open')}</a>}
        </Section>
    );
}
