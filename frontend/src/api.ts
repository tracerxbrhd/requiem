export type Session = {
    user: null | { provider: string; name: string; avatar: string | null };
    csrf: string | null;
    dev_auth_enabled: boolean;
    discord_enabled: boolean;
};
export type Guild = {
    id: string;
    name: string;
    icon: string | null;
    installed: boolean;
};
export type Entity = { id: string; name: string; colour: number; type: number };
export type EventSetting = {
    kind: string;
    enabled: boolean;
    channel: string | null;
};
export type Sections = {
    general: { enabled: boolean };
    commands: { commands: { name: string; enabled: boolean }[] };
    access: {
        roles: string[];
        commands: {
            name: string;
            mode: 'inherit' | 'custom';
            roles: string[];
        }[];
    };
    logging: {
        enabled: boolean;
        default_channel: string | null;
        categories: { category: string; channel: string | null }[];
        events: EventSetting[];
    };
    'message-logging': {
        events: EventSetting[];
        include_bots: boolean;
        include_webhooks: boolean;
        scope: 'all_except_exclusions' | 'selected_channels_only';
        channels: string[];
    };
};
export type Section = keyof Sections;
export type Snapshot<T> = { revision: string; data: T };
export type Overview = {
    guild: Guild;
    general: Snapshot<Sections['general']>;
    commands: Snapshot<Sections['commands']>;
    access: Snapshot<Sections['access']>;
    diagnostics: {
        status: string;
        destinations: [string, string][];
        capabilities: string[];
    };
    events: { kind: string; category: string }[];
};
export class ApiError extends Error {
    constructor(
        public code: string,
        message: string,
        public status: number,
    ) {
        super(message);
    }
}
let csrf: string | null = null;
export function setCsrf(value: string | null) {
    csrf = value;
}
export async function request<T>(
    path: string,
    method = 'GET',
    data?: unknown,
): Promise<T> {
    const response = await fetch('/api' + path, {
        method,
        credentials: 'same-origin',
        headers: {
            'Content-Type': 'application/json',
            ...(csrf ? { 'X-CSRF-Token': csrf } : {}),
        },
        ...(data === undefined ? {} : { body: JSON.stringify(data) }),
    }).catch(() => {
        throw new ApiError(
            'unavailable',
            'We could not connect to Requiem. Check your connection and try again.',
            503,
        );
    });
    const body = await response.json().catch(() => null);
    if (!response.ok) {
        if (response.status === 401)
            window.dispatchEvent(new Event('requiem:unauthorized'));
        throw new ApiError(
            body?.error?.code ?? 'unavailable',
            body?.error?.message ??
                'The server is unavailable. Please try again.',
            response.status,
        );
    }
    return body as T;
}
export const sectionPath = (guild: string, section: Section) =>
    `/guilds/${guild}/modules/moderation/${section}`;
