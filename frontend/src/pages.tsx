import { useCallback, useEffect, useRef, useState } from 'react';
import {
    Link,
    Navigate,
    NavLink,
    Outlet,
    useLocation,
    useParams,
} from 'react-router-dom';
import {
    ArrowDown,
    ArrowLeft,
    ArrowRight,
    ChevronRight,
    ExternalLink,
    Globe,
    LayoutDashboard,
    LogOut,
    Menu,
    Plus,
    Settings2,
    Shield,
    SlidersHorizontal,
    Terminal,
    Workflow,
    X,
} from 'lucide-react';
import { request, type Guild, type Overview } from './api';
import { useAuth } from './auth';
import { Brand, Callout, Dialog, State } from './ui';
export const project = 'https://github.com/tracerxbrhd/requiem';
export function Landing() {
    return (
        <div className="landing">
            <header className="public-header">
                <Link to="/">
                    <Brand />
                </Link>
                <nav>
                    <a href="#systems">Platform</a>
                    <a href={`${project}/tree/master/docs`}>
                        Documentation <ExternalLink size={13} />
                    </a>
                    <a href={project}>
                        GitHub <ExternalLink size={13} />
                    </a>
                </nav>
                <Link className="button primary" to="/dashboard">
                    Open Dashboard <ArrowRight size={16} />
                </Link>
            </header>
            <main>
                <section className="hero">
                    <div className="hero-copy">
                        <span className="eyebrow">
                            <span className="live-dot" /> DISCORD MANAGEMENT,
                            CONSIDERED.
                        </span>
                        <h1>
                            A quieter kind
                            <br />
                            of <em>control.</em>
                        </h1>
                        <p>
                            Purposeful moderation. Clear audit trails.
                            <br />
                            One considered workspace for your Discord community.
                        </p>
                        <div className="actions">
                            <Link className="button primary" to="/dashboard">
                                Open Dashboard <ArrowRight size={18} />
                            </Link>
                            <a className="button ghost" href="#systems">
                                Explore Requiem <ArrowDown size={16} />
                            </a>
                        </div>
                        <div className="hero-footnote">
                            <Shield size={16} /> Operations in Discord.
                            Configuration here.
                        </div>
                    </div>
                    <div className="hero-art">
                        <img
                            src="/requiem.jpg"
                            alt="Requiem's violet guardian, surrounded by symbols of community and protection"
                        />
                        <span className="art-caption">
                            REQUIEM / BUILT FOR INTENTIONAL COMMUNITIES
                        </span>
                    </div>
                </section>
                <section id="systems" className="systems">
                    <div className="section-intro">
                        <span className="eyebrow">EVERY SYSTEM, A PURPOSE</span>
                        <h2>
                            Less command clutter.
                            <br />
                            More operational clarity.
                        </h2>
                        <p>
                            The tools your team needs, with configuration that
                            stays out of the conversation.
                        </p>
                    </div>
                    <div className="feature-grid">
                        {[
                            {
                                icon: SlidersHorizontal,
                                title: 'Administration',
                                text: 'A focused workspace for roles, commands and configuration. Every change stays in your control.',
                            },
                            {
                                icon: Shield,
                                title: 'Moderation',
                                text: 'Seven purposeful commands. Native Discord permissions, clear access rules and durable temporary bans.',
                            },
                            {
                                icon: Workflow,
                                title: 'Audit & Logging',
                                text: 'Choose the events that matter and where they belong. Keep your team informed in Discord.',
                            },
                        ].map(({ icon: Icon, title, text }, i) => (
                            <article key={title}>
                                <span className="feature-number">0{i + 1}</span>
                                <Icon />
                                <h3>{title}</h3>
                                <p>{text}</p>
                            </article>
                        ))}
                    </div>
                </section>
                <section className="preview glass">
                    <div>
                        <span className="eyebrow">
                            YOUR SERVER. YOUR RULES.
                        </span>
                        <h2>Configure with confidence.</h2>
                        <p>
                            Set up once. Review clearly. Save deliberately.
                            <br />
                            Requiem keeps the daily work where your team already
                            is.
                        </p>
                        <Link className="button primary" to="/dashboard">
                            Enter your workspace <ArrowRight size={16} />
                        </Link>
                    </div>
                    <div
                        className="preview-ui"
                        aria-label="Illustrative administration preview"
                    >
                        <div className="preview-top">
                            <Shield size={20} />
                            <strong>Moderation</strong>
                            <span className="badge">Configuration</span>
                        </div>
                        <div className="preview-tabs">
                            <span>General</span>
                            <span>Commands</span>
                            <span>Logging</span>
                        </div>
                        <div className="preview-row">
                            <span>
                                Purposeful commands
                                <small>Access controlled by your team</small>
                            </span>
                            <strong>07</strong>
                        </div>
                        <div className="preview-row">
                            <span>
                                Audit destinations
                                <small>Events delivered to Discord</small>
                            </span>
                            <ChevronRight />
                        </div>
                        <div className="preview-row">
                            <span>
                                Explicit saves
                                <small>Your changes, reviewed first</small>
                            </span>
                            <Shield size={18} />
                        </div>
                    </div>
                </section>
                <section className="philosophy">
                    <Terminal />
                    <span>Discord for operations.</span>
                    <span className="muted">Requiem for configuration.</span>
                </section>
            </main>
            <footer>
                <Brand />
                <span>Built for the work behind a great community.</span>
                <a href={project}>
                    Source <ExternalLink size={13} />
                </a>
            </footer>
        </div>
    );
}
export function Login() {
    const { session, refresh } = useAuth();
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);
    const location = useLocation();
    if (!session) return <State title="Preparing secure sign-in" busy />;
    if (session.user) return <Navigate to="/dashboard/servers" replace />;
    async function development() {
        setBusy(true);
        try {
            await request('/auth/dev', 'POST');
            await refresh();
        } catch (e) {
            setError((e as Error).message);
        } finally {
            setBusy(false);
        }
    }
    return (
        <div className="login-page">
            <Link className="back-link" to="/">
                <ArrowLeft size={16} />
                Back to Requiem
            </Link>
            <div className="login-art">
                <img src="/requiem.jpg" alt="Requiem guardian" />
            </div>
            <section className="login-panel glass">
                <Brand />
                <span className="eyebrow">ADMINISTRATION PLATFORM</span>
                <h1>
                    Your community.
                    <br />
                    Your workspace.
                </h1>
                <p>Sign in to configure the servers you own or administer.</p>
                {location.search.includes('auth_error') && (
                    <Callout>
                        Discord sign-in could not be completed. Please start
                        again.
                    </Callout>
                )}
                {error && <Callout>{error}</Callout>}
                {session.discord_enabled ? (
                    <a
                        className="button primary"
                        href="/api/auth/discord/start"
                    >
                        Continue with Discord <ArrowRight size={18} />
                    </a>
                ) : (
                    <Callout>
                        Discord sign-in is not configured by the operator yet.
                    </Callout>
                )}
                {session.dev_auth_enabled && (
                    <>
                        <div className="divider">LOCAL DEVELOPMENT</div>
                        <button
                            disabled={busy}
                            onClick={() => void development()}
                        >
                            {busy
                                ? 'Opening workspace…'
                                : 'Continue in development mode'}
                        </button>
                        <small className="muted">
                            A local development session. No Discord account is
                            impersonated.
                        </small>
                    </>
                )}
                <p className="login-note">
                    <Shield size={15} /> Secure server sessions. Your Discord
                    tokens stay on the server.
                </p>
            </section>
        </div>
    );
}
export function Account() {
    const { session, refresh } = useAuth();
    const [error, setError] = useState('');
    return (
        <div className="account">
            <details>
                <summary>
                    {session?.user?.avatar ? (
                        <img
                            className="avatar"
                            src={session.user.avatar}
                            alt=""
                        />
                    ) : (
                        <span className="avatar">{session?.user?.name[0]}</span>
                    )}
                    <span>
                        {session?.user?.name}
                        <small>
                            {session?.user?.provider === 'development'
                                ? 'Development session'
                                : 'Discord account'}
                        </small>
                    </span>
                </summary>
                <div className="account-menu glass">
                    <Link to="/dashboard/servers">
                        <LayoutDashboard size={16} />
                        Back to servers
                    </Link>
                    <label>
                        <Globe size={16} />
                        Language
                        <select aria-label="Language">
                            <option>English</option>
                        </select>
                    </label>
                    <button
                        onClick={() =>
                            void request('/auth/logout', 'POST')
                                .then(refresh)
                                .catch((e) => setError((e as Error).message))
                        }
                    >
                        <LogOut size={16} />
                        Log out
                    </button>
                    {error && <p role="alert">{error}</p>}
                </div>
            </details>
        </div>
    );
}
export function GuildCard({
    guild,
    onInstall,
}: {
    guild: Guild;
    onInstall: () => void;
}) {
    const body = (
        <>
            <span className="guild-icon">
                {guild.icon ? (
                    <img src={guild.icon} alt="" />
                ) : (
                    guild.name.slice(0, 2).toUpperCase()
                )}
            </span>
            <h2>{guild.name}</h2>
            <span className="guild-card-foot">
                {guild.installed ? 'Open workspace' : 'Add Requiem'}
                {guild.installed ? (
                    <ArrowRight size={18} />
                ) : (
                    <Plus size={18} />
                )}
            </span>
        </>
    );
    return guild.installed ? (
        <Link
            className="guild-card glass installed"
            aria-label={`${guild.name}, Requiem installed, open workspace`}
            to={`/dashboard/guilds/${guild.id}`}
        >
            {body}
        </Link>
    ) : (
        <button
            className="guild-card glass inactive"
            aria-label={`${guild.name}, Requiem not installed, add bot`}
            onClick={onInstall}
        >
            {body}
        </button>
    );
}
export function Servers() {
    const [guilds, setGuilds] = useState<Guild[] | null>(null);
    const [error, setError] = useState('');
    const [query, setQuery] = useState('');
    const [install, setInstall] = useState<Guild | null>(null);
    const [busy, setBusy] = useState(false);
    const { session } = useAuth();
    async function load() {
        setError('');
        try {
            setGuilds(await request<Guild[]>('/guilds'));
        } catch (e) {
            setError((e as Error).message);
        }
    }
    useEffect(() => {
        void load();
    }, []);
    return (
        <div className="servers-page">
            <header>
                <Link to="/">
                    <Brand />
                </Link>
                <Account />
            </header>
            <main>
                <div className="page-heading">
                    <span className="eyebrow">YOUR ADMINISTRATION SPACE</span>
                    <h1>Choose your server.</h1>
                    <p>A focused workspace for every community you manage.</p>
                </div>
                {session?.user?.provider === 'development' && (
                    <Callout>
                        Development mode · Showing servers known to your local
                        database.
                    </Callout>
                )}
                <div className="server-tools">
                    <input
                        aria-label="Search servers"
                        placeholder="Find a server…"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                    />
                    <button onClick={() => void load()}>Refresh servers</button>
                </div>
                {error ? (
                    <State
                        title="Servers couldn't be retrieved"
                        detail={error}
                        retry={() => void load()}
                    />
                ) : !guilds ? (
                    <State title="Finding your communities" busy />
                ) : !guilds.length ? (
                    <State
                        title="No servers to configure yet"
                        detail={
                            session?.user?.provider === 'development'
                                ? 'Connect the bot to a test server or use the documented development seed command.'
                                : 'Only servers you own or administer appear here. Check your Discord permissions and refresh.'
                        }
                    />
                ) : (
                    <div className="guild-grid">
                        {guilds
                            .filter((g) =>
                                g.name
                                    .toLowerCase()
                                    .includes(query.toLowerCase()),
                            )
                            .map((g) => (
                                <GuildCard
                                    key={g.id}
                                    guild={g}
                                    onInstall={() => {
                                        setInstall(g);
                                        setError('');
                                    }}
                                />
                            ))}
                    </div>
                )}
                {guilds?.length &&
                !guilds.some((g) =>
                    g.name.toLowerCase().includes(query.toLowerCase()),
                ) ? (
                    <State
                        title="No matching servers"
                        detail="Try another server name."
                    />
                ) : null}
            </main>
            {install && (
                <Dialog
                    title={`Add Requiem to ${install.name}`}
                    onClose={() => setInstall(null)}
                    busy={busy}
                    actionLabel="Continue to Discord"
                    action={() => {
                        setBusy(true);
                        void request<{ url: string }>(
                            `/guilds/${install.id}/install`,
                            'POST',
                        )
                            .then((value) => window.location.assign(value.url))
                            .catch((e) => {
                                setError((e as Error).message);
                                setInstall(null);
                                setBusy(false);
                            });
                    }}
                >
                    <p>
                        Discord will show the permissions Requiem needs for
                        moderation and logging. After installation, you'll
                        return to server selection.
                    </p>
                </Dialog>
            )}
        </div>
    );
}
export function Workspace() {
    const { guildId = '' } = useParams();
    const [overview, setOverview] = useState<Overview | null>(null);
    const [error, setError] = useState('');
    const [drawer, setDrawer] = useState(false);
    const sidebar = useRef<HTMLElement>(null);
    useEffect(() => {
        if (!drawer) return;
        const previous = document.activeElement as HTMLElement | null;
        const controls = () =>
            Array.from(
                sidebar.current?.querySelectorAll<HTMLElement>(
                    'a, button, summary, select',
                ) ?? [],
            ).filter((item) => item.getClientRects().length > 0);
        controls()[0]?.focus();
        const trap = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                setDrawer(false);
                return;
            }
            if (event.key !== 'Tab') return;
            const items = controls();
            const first = items[0],
                last = items[items.length - 1];
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last?.focus();
            }
            if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first?.focus();
            }
        };
        document.addEventListener('keydown', trap);
        return () => {
            document.removeEventListener('keydown', trap);
            previous?.focus();
        };
    }, [drawer]);

    const location = useLocation();
    const load = useCallback(async () => {
        try {
            setOverview(await request<Overview>(`/guilds/${guildId}/overview`));
            setError('');
        } catch (e) {
            setError((e as Error).message);
        }
    }, [guildId]);
    useEffect(() => {
        void load();
    }, [load]);
    useEffect(() => setDrawer(false), [location.pathname]);
    const base = `/dashboard/guilds/${guildId}`;
    if (error)
        return (
            <>
                <Link className="back-link" to="/dashboard/servers">
                    Back to servers
                </Link>
                <State
                    title="Workspace unavailable"
                    detail={error}
                    retry={() => void load()}
                />
            </>
        );
    if (!overview) return <State title="Preparing server configuration" busy />;
    return (
        <div className="workspace">
            <button
                className="mobile-menu"
                aria-label="Open navigation"
                onClick={() => setDrawer(true)}
            >
                <Menu /> Requiem
            </button>
            {drawer && (
                <button
                    className="drawer-scrim"
                    aria-label="Close navigation"
                    onClick={() => setDrawer(false)}
                />
            )}
            <aside
                ref={sidebar}
                className={`sidebar glass ${drawer ? 'open' : ''}`}
            >
                <Link to="/">
                    <Brand />
                </Link>
                <button
                    className="mobile-close icon-button"
                    onClick={() => setDrawer(false)}
                    aria-label="Close navigation"
                >
                    <X />
                </button>
                <div className="guild-identity">
                    <span className="avatar">
                        {overview.guild.icon ? (
                            <img src={overview.guild.icon} alt="" />
                        ) : (
                            overview.guild.name.slice(0, 2)
                        )}
                    </span>
                    <div>
                        <strong>{overview.guild.name}</strong>
                        <small>Server workspace</small>
                    </div>
                </div>
                <span className="nav-label">WORKSPACE</span>
                <nav>
                    <NavLink end to={base}>
                        <LayoutDashboard size={18} />
                        Overview
                    </NavLink>
                </nav>
                <span className="nav-label">MODULES</span>
                <nav>
                    <NavLink
                        to={`${base}/moderation/general`}
                        className={
                            location.pathname.includes('/moderation/')
                                ? 'active'
                                : ''
                        }
                    >
                        <Shield size={18} />
                        Moderation
                        <ChevronRight size={14} />
                    </NavLink>
                </nav>
                <div className="sidebar-bottom">
                    <Link to="/dashboard/servers">
                        <ArrowLeft size={17} />
                        Back to servers
                    </Link>
                    <Account />
                </div>
            </aside>
            <main className="workspace-main">
                <div className="workspace-top">
                    <span>
                        {overview.guild.name} <ChevronRight size={13} />{' '}
                        Administration
                    </span>
                    <span className="badge">
                        <span className="live-dot" />
                        Requiem installed
                    </span>
                </div>
                <Outlet context={{ overview, reload: load }} />
            </main>
        </div>
    );
}
export function OverviewPage({ overview }: { overview: Overview }) {
    const { guildId } = useParams();
    const enabled = overview.general.data.enabled;
    const count = overview.commands.data.commands.filter(
        (x) => x.enabled,
    ).length;
    return (
        <>
            <div className="page-heading">
                <span className="eyebrow">WORKSPACE OVERVIEW</span>
                <h1>Everything in its place.</h1>
                <p>Your Requiem configuration, at a glance.</p>
            </div>
            <div className="overview-grid">
                <section
                    className={`module-panel glass ${!enabled ? 'subdued' : ''}`}
                >
                    <div className="module-icon">
                        <Shield size={26} />
                    </div>
                    <span className="badge">
                        {enabled ? 'Enabled' : 'Disabled'}
                    </span>
                    <h2>Moderation</h2>
                    <p>
                        Moderation workflows, command access and audit logging.
                        Configured for your team.
                    </p>
                    <div className="module-summary">
                        <span>
                            <Terminal size={17} />
                            {count} commands enabled
                        </span>
                        <span>
                            <Workflow size={17} />
                            Logging:{' '}
                            {overview.diagnostics.status.replaceAll('_', ' ')}
                        </span>
                    </div>
                    <Link
                        className="button primary"
                        to={`/dashboard/guilds/${guildId}/moderation/general`}
                    >
                        Configure module <Settings2 size={16} />
                    </Link>
                </section>
                <section className="health-panel glass">
                    <span className="eyebrow">CONFIGURATION HEALTH</span>
                    <h2>Ready for the work?</h2>
                    <div className="health-line">
                        <Shield size={20} />
                        <div>
                            <strong>Installation active</strong>
                            <p>Requiem is known to this server.</p>
                        </div>
                    </div>
                    <div className="health-line">
                        <Workflow size={20} />
                        <div>
                            <strong>Logging readiness</strong>
                            <p>
                                {overview.diagnostics.status.replaceAll(
                                    '_',
                                    ' ',
                                )}
                            </p>
                        </div>
                    </div>
                    {overview.diagnostics.capabilities.map((x) => (
                        <Callout key={x}>
                            {x.replaceAll('_', ' ')}. Desired settings remain
                            saved.
                        </Callout>
                    ))}
                    {!overview.access.data.roles.length && (
                        <Callout>
                            No default access roles selected. Commands need an
                            allowed role before use.
                        </Callout>
                    )}
                </section>
            </div>
            <div className="operational-note">
                <Terminal size={20} />
                <p>
                    <strong>Keep operations in Discord.</strong> Use this
                    workspace to configure Requiem. Your team's moderation
                    commands and audit output stay in Discord.
                </p>
            </div>
        </>
    );
}
