// German texts (Swiss spelling: ss, never ß; informal du). en.ts must have the same keys (tsc checks it).
const de = {
    logins: {
        title: 'Anmeldungen',
        intro: 'Eine Anmeldung gilt auf jedem Gerät etwa zwei Tage. Geht ein Handy oder Computer verloren, beende alle deine Anmeldungen auf einmal; danach meldest du dich mit deiner PIN wieder an. Eine neue PIN tut dasselbe für diese Person.',
        logoutEverywhere: 'Überall abmelden',
        confirmLogoutEverywhere: 'Auf allen Geräten abmelden, auch auf diesem?',
        logoutFailed: 'Überall abmelden fehlgeschlagen',
        language: 'Sprache',
        languageFailed: 'Sprache konnte nicht gespeichert werden',
        german: 'Deutsch',
        english: 'English',
    },
};

export default de;
export type Messages = typeof de;
