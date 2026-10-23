import { EmailMessage } from 'cloudflare:email';
import { buildNotice } from './notice';

export interface Env {
    APP_URL: string;
    INBOUND_SECRET: string;
    CF_ACCESS_CLIENT_ID: string;
    CF_ACCESS_CLIENT_SECRET: string;
    // Optional: a verified Email Routing destination that gets the mail when the app can't take it
    FALLBACK_ADDRESS?: string;
    // send_email binding (wrangler.toml) for a note to the fallback address about why it got the mail
    NOTIFY?: { send(message: EmailMessage): Promise<unknown> };
}

// The parts of Cloudflare's ForwardableEmailMessage the worker uses
export interface InboundMessage {
    readonly from: string;
    readonly to: string;
    readonly raw: ReadableStream<Uint8Array>;
    readonly rawSize: number;
    readonly headers: Headers;
    setReject(reason: string): void;
    forward(rcptTo: string, headers?: Headers): Promise<unknown>;
}

const APP = 'Family Budget';
const PATH = '/api/v1/inbound';

// The server name Cloudflare's Email Routing writes its SPF/DKIM/DMARC results under (seen on 2026-10-23)
export const AUTHSERV_ID = 'mx.cloudflare.net';

/**
 * Whether Cloudflare found the mail authentic: the topmost Authentication-Results (or ARC-Authentication-Results)
 * header must be Cloudflare's and say dmarc=pass for the domain of the From address. Cloudflare puts its result
 * above the mail's own headers, so results further down (forged, or from earlier hops) never count. Without
 * Cloudflare's result on top the mail is not authentic.
 */
export function dmarcPassed(rawHeaders: string, fromHeader: string): boolean {
    const fields = rawHeaders.replace(/\r?\n[ \t]+/g, ' ').split(/\r?\n/);
    const result = fields.find((field) => /^(arc-)?authentication-results\s*:/i.test(field));
    if (!result) return false;
    const value = result.slice(result.indexOf(':') + 1).replace(/^\s*i=\d+\s*;/i, '');
    const server = value.split(';')[0].trim().split(/\s+/)[0].toLowerCase();
    if (server !== AUTHSERV_ID) return false;
    const domain = fromDomain(fromHeader);
    const dmarc = value.split(';').map((part) => part.trim()).find((part) => /^dmarc=/i.test(part));
    if (!domain || !dmarc || !/^dmarc=pass\b/i.test(dmarc)) return false;
    const headerFrom = dmarc.match(/header\.from=([^\s;]+)/i)?.[1]?.toLowerCase();
    return headerFrom === domain;
}

function fromDomain(fromHeader: string): string | null {
    const address = fromHeader.match(/<([^<>\s]+@[^<>\s]+)>/)?.[1] ?? fromHeader.match(/[^\s<>,"]+@[^\s<>,"]+/)?.[0];
    return address ? address.split('@')[1].toLowerCase() : null;
}

function headerBlock(body: ArrayBuffer): string {
    const text = new TextDecoder().decode(body);
    const end = text.search(/\r?\n\r?\n/);
    return end === -1 ? text : text.slice(0, end);
}

/** Tell the fallback address why it got the mail; the mail itself is forwarded already, so this may fail. */
async function notify(message: InboundMessage, env: Env, to: string, reason: string): Promise<void> {
    if (!env.NOTIFY) return;
    try {
        const raw = buildNotice({
            from: message.to,
            to,
            reason,
            originalFrom: message.from,
            originalSubject: message.headers.get('subject') ?? '',
            appUrl: env.APP_URL,
        });
        await env.NOTIFY.send(new EmailMessage(message.to, to, raw));
    } catch (error) {
        console.warn(`Hinweis an die Ersatzadresse nicht gesendet: ${String(error)}`);
    }
}

/**
 * The app couldn't take the mail: forward it to the fallback address if there is one,
 * otherwise reject it, so the sender gets a bounce instead of the mail being lost silently.
 */
async function giveUp(message: InboundMessage, env: Env, reason: string): Promise<void> {
    if (env.FALLBACK_ADDRESS) {
        try {
            await message.forward(env.FALLBACK_ADDRESS, new Headers({ 'X-Family-Budget-Error': reason }));
            await notify(message, env, env.FALLBACK_ADDRESS, reason);
            return;
        } catch (error) {
            reason = `${reason}; Weiterleitung fehlgeschlagen: ${String(error)}`;
        }
    }
    message.setReject(reason);
}

/**
 * Post an authentic mail to the app. A mail Cloudflare didn't find authentic, or from a sender the app doesn't
 * know (403), is rejected and never goes to the fallback address; a mail the app couldn't take otherwise does.
 */
export async function deliver(message: InboundMessage, env: Env, fetchImpl: typeof fetch = fetch): Promise<void> {
    const body = await new Response(message.raw).arrayBuffer();
    if (!dmarcPassed(headerBlock(body), message.headers.get('from') ?? '')) {
        message.setReject('Absender nicht bestätigt');
        return;
    }
    if (!env.APP_URL) {
        await giveUp(message, env, `${APP}: APP_URL ist im Worker nicht gesetzt`);
        return;
    }
    let response: Response;
    try {
        response = await fetchImpl(`${env.APP_URL.replace(/\/+$/, '')}${PATH}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'message/rfc822',
                'X-Inbound-Secret': env.INBOUND_SECRET,
                'CF-Access-Client-Id': env.CF_ACCESS_CLIENT_ID,
                'CF-Access-Client-Secret': env.CF_ACCESS_CLIENT_SECRET,
            },
            body,
            // Cloudflare Access answers a bad service token with a redirect to its login page
            redirect: 'manual',
        });
    } catch (error) {
        await giveUp(message, env, `${APP} nicht erreichbar: ${String(error)}`);
        return;
    }
    if (response.status === 403) {
        message.setReject('Nicht angenommen');
        return;
    }
    if (!response.ok) {
        await giveUp(message, env, `${APP} hat die Mail nicht angenommen (HTTP ${response.status})`);
    }
}

export default {
    async email(message: InboundMessage, env: Env): Promise<void> {
        await deliver(message, env);
    },
};
