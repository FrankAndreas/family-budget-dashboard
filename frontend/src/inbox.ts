// Receipt mails forwarded to the app (issue #57): they wait unopened until a parent releases one
import { useCallback, useEffect, useState } from 'react';
import api from './api';
import type { AttachmentInfo, Draft } from './receipts';

export interface InboxMail {
    id: string;
    person_id: string | null;
    person_name: string | null;
    from_addr: string;
    subject: string;
    sent_at: string | null;
    received_at: string;
    attachment_names: string[];
    size: number;
    suggested_account_id: string | null;
}

// A receipt photographed on a parent's phone (receipt scan), waiting until it is booked
export interface InboxPhoto {
    id: string;
    person_id: string | null;
    person_name: string | null;
    taken_at: string;
    read_state: 'waiting' | 'reading' | 'read' | 'failed';
    shop: string | null;
    total: number | null;
    suggested_account_id: string | null;
}

export interface PersonEmail {
    id: string;
    user_id: string;
    address: string;
}

// What releasing a mail gives: the AI's draft (null without the AI) and the mail as a pending attachment
export interface Release {
    draft: Draft | null;
    attachment: AttachmentInfo;
}

export function useInbox(enabled: boolean, version: number) {
    const [mails, setMails] = useState<InboxMail[]>([]);
    const [failed, setFailed] = useState(false);
    const [own, setOwn] = useState(0);
    useEffect(() => {
        if (!enabled) return;
        api.get('/api/v1/inbox')
            .then(response => { setMails(response.data); setFailed(false); })
            .catch(() => setFailed(true));
    }, [enabled, version, own]);
    const reload = useCallback(() => setOwn(v => v + 1), []);
    return { mails, failed, reload };
}

export async function release(mail: InboxMail): Promise<Release> {
    const response = await api.post(`/api/v1/inbox/${mail.id}/release`);
    return {
        draft: response.data.draft,
        attachment: response.data.attachment,
    };
}
