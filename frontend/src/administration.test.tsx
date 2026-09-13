import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
    createMemoryRouter,
    Link,
    Outlet,
    RouterProvider,
} from 'react-router-dom';
import { GuildCard } from './pages';
import { ModulePage } from './settings';
import { UnsavedGuard } from './ui';
import { Protected, AuthProvider } from './auth';
import type { Overview } from './api';
const overview: Overview = {
    guild: { id: '10', name: 'Test community', icon: null, installed: true },
    general: { revision: 'a'.repeat(64), data: { enabled: false } },
    commands: { revision: 'a'.repeat(64), data: { commands: [] } },
    access: { revision: 'a'.repeat(64), data: { roles: [], commands: [] } },
    diagnostics: {
        status: 'default_destination_missing',
        destinations: [],
        capabilities: ['message_content_unavailable'],
    },
    events: [],
};
const fetchMock = vi.fn();
beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock);
    fetchMock.mockReset();
    Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
        configurable: true,
        value: function (this: HTMLDialogElement) {
            this.setAttribute('open', '');
        },
    });
    Object.defineProperty(HTMLDialogElement.prototype, 'close', {
        configurable: true,
        value: function (this: HTMLDialogElement) {
            this.removeAttribute('open');
        },
    });
});
afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});
function respond(value: unknown, status = 200) {
    return Promise.resolve({
        ok: status < 400,
        status,
        json: () => Promise.resolve(value),
    });
}
function mountModule(section = 'general') {
    const router = createMemoryRouter(
        [
            {
                path: '/dashboard/guilds/:guildId',
                element: (
                    <Outlet context={{ overview, reload: async () => {} }} />
                ),
                children: [
                    {
                        path: 'moderation/general',
                        element: <ModulePage section="general" />,
                    },
                    {
                        path: 'moderation/message-logging',
                        element: <ModulePage section="message-logging" />,
                    },
                    {
                        path: 'moderation/commands',
                        element: <p>Commands destination</p>,
                    },
                ],
            },
        ],
        { initialEntries: [`/dashboard/guilds/10/moderation/${section}`] },
    );
    render(<RouterProvider router={router} />);
    return router;
}
describe('administration interactions', () => {
    it('redirects an unauthenticated protected route', async () => {
        fetchMock.mockImplementation(() =>
            respond({
                user: null,
                csrf: null,
                dev_auth_enabled: false,
                discord_enabled: true,
            }),
        );
        const router = createMemoryRouter(
            [
                {
                    element: (
                        <AuthProvider>
                            <Outlet />
                        </AuthProvider>
                    ),
                    children: [
                        {
                            element: <Protected />,
                            children: [
                                {
                                    path: '/private',
                                    element: <p>Secret workspace</p>,
                                },
                            ],
                        },
                        { path: '/dashboard', element: <p>Sign in screen</p> },
                    ],
                },
            ],
            { initialEntries: ['/private'] },
        );
        render(<RouterProvider router={router} />);
        expect(await screen.findByText('Sign in screen')).toBeVisible();
        expect(screen.queryByText('Secret workspace')).toBeNull();
    });
    it('distinguishes installed cards and opens installation confirmation callback', async () => {
        const install = vi.fn();
        const guild = overview.guild;
        render(
            <RouterProvider
                router={createMemoryRouter([
                    {
                        path: '/',
                        element: (
                            <>
                                <GuildCard guild={guild} onInstall={install} />
                                <GuildCard
                                    guild={{
                                        ...guild,
                                        id: '11',
                                        name: 'New community',
                                        installed: false,
                                    }}
                                    onInstall={install}
                                />
                            </>
                        ),
                    },
                ])}
            />,
        );
        expect(
            screen.getByRole('link', { name: /Requiem installed/ }),
        ).toHaveAttribute('href', '/dashboard/guilds/10');
        await userEvent.click(
            screen.getByRole('button', { name: /Requiem not installed/ }),
        );
        expect(install).toHaveBeenCalledOnce();
    });
    it('holds navigation until unsaved edits are discarded', async () => {
        const router = createMemoryRouter([
            {
                path: '/',
                element: (
                    <>
                        <UnsavedGuard dirty />
                        <Link to="/next">Leave</Link>
                    </>
                ),
            },
            { path: '/next', element: <p>Next page</p> },
        ]);
        render(<RouterProvider router={router} />);
        await userEvent.click(screen.getByText('Leave'));
        expect(screen.getByRole('dialog')).toBeVisible();
        await userEvent.click(screen.getByRole('button', { name: 'Stay' }));
        expect(router.state.location.pathname).toBe('/');
        await userEvent.click(screen.getByText('Leave'));
        await userEvent.click(
            screen.getByRole('button', { name: 'Discard changes' }),
        );
        expect(await screen.findByText('Next page')).toBeVisible();
    });
    it('protects browser unload for a dirty draft', () => {
        render(
            <RouterProvider
                router={createMemoryRouter([
                    { path: '/', element: <UnsavedGuard dirty /> },
                ])}
            />,
        );
        const event = new Event('beforeunload', { cancelable: true });
        window.dispatchEvent(event);
        expect(event.defaultPrevented).toBe(true);
    });
    it('saves only when explicitly requested and reports success', async () => {
        fetchMock.mockImplementation((_url: string, init: RequestInit) =>
            respond(
                init.method === 'PUT'
                    ? { revision: 'b'.repeat(64), data: { enabled: true } }
                    : overview.general,
            ),
        );
        mountModule();
        await userEvent.click(await screen.findByRole('switch'));
        expect(fetchMock).toHaveBeenCalledTimes(1);
        await userEvent.click(
            screen.getByRole('button', { name: 'Save changes' }),
        );
        expect(await screen.findByText('Changes saved')).toBeVisible();
        expect(fetchMock.mock.calls[1][1].method).toBe('PUT');
        expect(JSON.parse(fetchMock.mock.calls[1][1].body).revision).toBe(
            'a'.repeat(64),
        );
    });
    it('keeps the draft and explains a stale revision', async () => {
        fetchMock.mockImplementation((_url: string, init: RequestInit) =>
            init.method === 'PUT'
                ? respond(
                      {
                          error: {
                              code: 'stale_revision',
                              message: 'Changed elsewhere',
                          },
                      },
                      409,
                  )
                : respond(overview.general),
        );
        mountModule();
        await userEvent.click(await screen.findByRole('switch'));
        await userEvent.click(
            screen.getByRole('button', { name: 'Save changes' }),
        );
        expect(
            await screen.findByText(/These settings were changed elsewhere/),
        ).toBeVisible();
        expect(screen.getByRole('switch')).toHaveAttribute(
            'aria-checked',
            'true',
        );
        expect(
            screen.getByRole('button', { name: 'Save changes' }),
        ).toBeDisabled();
    });
    it('requires confirmation before resetting', async () => {
        fetchMock.mockImplementation((_url: string, init: RequestInit) =>
            respond(
                init.method === 'POST'
                    ? { general: overview.general }
                    : overview.general,
            ),
        );
        mountModule();
        await userEvent.click(
            await screen.findByRole('button', { name: 'Reset to defaults' }),
        );
        expect(fetchMock).toHaveBeenCalledTimes(1);
        expect(screen.getByRole('dialog')).toHaveTextContent('temporary bans');
        await userEvent.click(
            screen.getByRole('button', {
                name: 'Reset Moderation',
            }),
        );
        await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
        expect(fetchMock.mock.calls[1][1].method).toBe('POST');
    });
    it('explains unavailable Message Content without disabling desired settings', async () => {
        fetchMock.mockImplementation((url: string) =>
            respond(
                url.endsWith('/channels')
                    ? []
                    : {
                          revision: 'a'.repeat(64),
                          data: {
                              events: [
                                  {
                                      kind: 'message_sent',
                                      enabled: false,
                                      channel: null,
                                  },
                              ],
                              include_bots: false,
                              include_webhooks: false,
                              scope: 'all_except_exclusions',
                              channels: [],
                          },
                      },
            ),
        );
        mountModule('message-logging');
        expect(
            await screen.findByText(
                /cannot operate until Message Content access/,
            ),
        ).toBeVisible();
        expect(
            screen.getByRole('switch', { name: 'Message sent' }),
        ).toBeEnabled();
    });
});
