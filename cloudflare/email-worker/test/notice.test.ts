import { describe, expect, it } from 'vitest';
import { buildNotice } from '../src/notice';

function decodeBody(raw: string): string {
    const body = raw.split('\r\n\r\n')[1].replace(/\r\n/g, '');
    return new TextDecoder().decode(Uint8Array.from(atob(body), (c) => c.charCodeAt(0)));
}

describe('buildNotice', () => {
    const raw = buildNotice({
        from: 'invoice@example.ch',
        to: 'papa@example.ch',
        reason: 'Family Budget hat die Mail nicht angenommen (HTTP 502)',
        originalFrom: 'mama@example.ch',
        originalSubject: 'WG: Ihre Bestellung bei Müller',
        appUrl: 'https://budget-inbound.example.ch',
        date: new Date('2026-10-18T10:00:00Z'),
        id: 'abc',
    });

    it('has the headers Cloudflare needs', () => {
        expect(raw).toContain('From: Belege <invoice@example.ch>\r\n');
        expect(raw).toContain('To: papa@example.ch\r\n');
        expect(raw).toContain('Message-ID: <abc@example.ch>\r\n');
        expect(raw).toContain('Date: Sun, 18 Oct 2026 10:00:00 GMT\r\n');
        expect(raw).toMatch(/^Subject: =\?UTF-8\?B\?[A-Za-z0-9+/=]+\?=\r$/m);
    });

    it('says why, what and what to do, umlauts intact', () => {
        const body = decodeBody(raw);
        expect(body).toContain('https://budget-inbound.example.ch');
        expect(body).toContain('HTTP 502');
        expect(body).toContain('mama@example.ch');
        expect(body).toContain('WG: Ihre Bestellung bei Müller');
        expect(body).toContain('weiter, sobald die App wieder läuft');
    });

    it('keeps base64 lines short', () => {
        for (const line of raw.split('\r\n')) expect(line.length).toBeLessThanOrEqual(998);
    });
});
