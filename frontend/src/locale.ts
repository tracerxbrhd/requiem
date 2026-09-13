export const locale = {
    code: 'en',
    name: 'English',
    copy: {
        save: 'Save changes',
        discard: 'Discard',
        stay: 'Stay',
        retry: 'Try again',
        unsaved: 'You have unsaved changes.',
        conflict:
            'These settings were changed elsewhere. Reload the latest configuration before saving.',
        saved: 'Changes saved',
        back: 'Back to servers',
    },
} as const;
export const humanize = (value: string) =>
    value
        .replaceAll('_', ' ')
        .replaceAll('-', ' ')
        .replace(/^./, (x) => x.toUpperCase());
