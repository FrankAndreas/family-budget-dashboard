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
    // manual: scanned with "Read with AI" off, never sent to the AI
    read_state: 'waiting' | 'reading' | 'read' | 'failed' | 'manual';
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

export function usePhotos(enabled: boolean, version: number) {
    const [photos, setPhotos] = useState<InboxPhoto[]>([]);
    const [own, setOwn] = useState(0);
    useEffect(() => {
        if (!enabled) return;
        api.get('/api/v1/inbox/photos').then(response => setPhotos(response.data)).catch(() => setPhotos([]));
    }, [enabled, version, own]);
    const reload = useCallback(() => setOwn(v => v + 1), []);
    // The AI reads new photos in the background: look again until it is through
    const pending = photos.some(photo => photo.read_state === 'waiting' || photo.read_state === 'reading');
    useEffect(() => {
        if (!enabled || !pending) return;
        const timer = setTimeout(reload, 5000);
        return () => clearTimeout(timer);
    }, [enabled, pending, photos, reload]);
    return { photos, reload };
}

// Opening a photo: the AI's draft (if it read it) and the photo as the parent's pending attachment
export async function openPhoto(photo: InboxPhoto): Promise<Release> {
    const response = await api.post(`/api/v1/inbox/photos/${photo.id}/open`);
    return { draft: response.data.draft, attachment: response.data.attachment };
}

export async function deletePhoto(photo: InboxPhoto): Promise<void> {
    await api.delete(`/api/v1/inbox/photos/${photo.id}`);
}

export async function release(mail: InboxMail): Promise<Release> {
    const response = await api.post(`/api/v1/inbox/${mail.id}/release`);
    return {
        draft: response.data.draft,
        attachment: response.data.attachment,
    };
}
