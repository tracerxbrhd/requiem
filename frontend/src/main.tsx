import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import {
    createBrowserRouter,
    RouterProvider,
    Outlet,
    useOutletContext,
    useLocation,
} from 'react-router-dom';
import '@fontsource-variable/manrope';
import './styles.css';
import { AuthProvider, Protected } from './auth';
import { Landing, Login, OverviewPage, Servers, Workspace } from './pages';
import { ModulePage, type WorkspaceContext } from './settings';
import { State } from './ui';
function Root() {
    const location = useLocation();
    if (location.pathname === '/') return <Outlet />;
    return (
        <AuthProvider>
            <a className="skip-link" href="#content">
                Skip to content
            </a>
            <div id="content">
                <Outlet />
            </div>
        </AuthProvider>
    );
}
function OverviewRoute() {
    const { overview } = useOutletContext<WorkspaceContext>();
    return <OverviewPage overview={overview} />;
}
const router = createBrowserRouter([
    {
        element: <Root />,
        errorElement: (
            <State
                title="This page couldn't be opened"
                detail="Return to the dashboard and try again."
            />
        ),
        children: [
            { path: '/', element: <Landing /> },
            { path: '/dashboard', element: <Login /> },
            {
                element: <Protected />,
                children: [
                    { path: '/dashboard/servers', element: <Servers /> },
                    {
                        path: '/dashboard/guilds/:guildId',
                        element: <Workspace />,
                        children: [
                            { index: true, element: <OverviewRoute /> },
                            ...(
                                [
                                    'general',
                                    'commands',
                                    'access',
                                    'logging',
                                    'message-logging',
                                ] as const
                            ).map((section) => ({
                                path: `moderation/${section}`,
                                element: <ModulePage section={section} />,
                            })),
                        ],
                    },
                ],
            },
            {
                path: '*',
                element: (
                    <State
                        title="Page not found"
                        detail="This workspace address does not exist."
                    />
                ),
            },
        ],
    },
]);
createRoot(document.getElementById('root')!).render(
    <StrictMode>
        <RouterProvider router={router} />
    </StrictMode>,
);
