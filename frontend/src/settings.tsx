import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { NavLink, useOutletContext, useParams } from 'react-router-dom';
import { RotateCcw, Shield, Workflow } from 'lucide-react';
import {
    ApiError,
    request,
    sectionPath,
    type Entity,
    type EventSetting,
    type Overview,
    type Section,
    type Sections,
    type Snapshot,
} from './api';
import { humanize, locale } from './locale';
import { Callout, Dialog, Selector, State, Toggle, UnsavedGuard } from './ui';
export type WorkspaceContext = {
    overview: Overview;
    reload: () => Promise<void>;
};
const tabs: { id: Section; label: string }[] = [
    { id: 'general', label: 'General' },
    { id: 'commands', label: 'Commands' },
    { id: 'access', label: 'Access' },
    { id: 'logging', label: 'Logging' },
    { id: 'message-logging', label: 'Message Logging' },
];
export function ModulePage({ section }: { section: Section }) {
    const { overview, reload } = useOutletContext<WorkspaceContext>();
    const { guildId = '' } = useParams();
    return (
        <>
            <div className="page-heading module-heading">
                <div>
                    <span className="eyebrow">MODULE CONFIGURATION</span>
                    <h1>
                        <Shield size={32} />
                        Moderation
                    </h1>
                    <p>Purposeful controls for a well-managed community.</p>
                </div>
                <span className="badge">
                    {overview.general.data.enabled
                        ? 'Module enabled'
                        : 'Module disabled'}
                </span>
            </div>
            <nav className="module-tabs" aria-label="Moderation sections">
                {tabs.map((tab) => (
                    <NavLink
                        key={tab.id}
                        to={`/dashboard/guilds/${guildId}/moderation/${tab.id}`}
                    >
                        {tab.label}
                    </NavLink>
                ))}
            </nav>
            <Editor
                key={`${guildId}-${section}`}
                section={section}
                guild={guildId}
                overview={overview}
                reload={reload}
            />
        </>
    );
}
function Editor({
    section,
    guild,
    overview,
    reload,
}: {
    section: Section;
    guild: string;
    overview: Overview;
    reload: () => Promise<void>;
}) {
    const [snapshot, setSnapshot] = useState<Snapshot<
        Sections[Section]
    > | null>(null);
    const [draft, setDraft] = useState<Sections[Section] | null>(null);
    const [entities, setEntities] = useState<Entity[]>([]);
    const [error, setError] = useState('');
    const [conflict, setConflict] = useState(false);
    const [busy, setBusy] = useState(false);
    const [success, setSuccess] = useState(false);
    const [reset, setReset] = useState(false);
    const load = useCallback(async () => {
        setError('');
        setConflict(false);
        setSuccess(false);
        try {
            const [value, options] = await Promise.all([
                request<Snapshot<Sections[Section]>>(
                    sectionPath(guild, section),
                ),
                section === 'access'
                    ? request<Entity[]>(`/guilds/${guild}/roles`)
                    : section === 'logging' || section === 'message-logging'
                      ? request<Entity[]>(`/guilds/${guild}/channels`)
                      : Promise.resolve([]),
            ]);
            setSnapshot(value);
            setDraft(value.data);
            setEntities(options);
        } catch (e) {
            setError((e as Error).message);
        }
    }, [guild, section]);
    useEffect(() => {
        void load();
    }, [load]);
    const dirty =
        snapshot !== null &&
        JSON.stringify(draft) !== JSON.stringify(snapshot.data);
    async function save() {
        if (!snapshot || !draft) return;
        setBusy(true);
        setError('');
        try {
            const value = await request<Snapshot<Sections[Section]>>(
                sectionPath(guild, section),
                'PUT',
                { revision: snapshot.revision, data: draft },
            );
            setSnapshot(value);
            setDraft(value.data);
            setSuccess(true);
            await reload();
        } catch (e) {
            setError((e as Error).message);
            setConflict(e instanceof ApiError && e.status === 409);
        } finally {
            setBusy(false);
        }
    }
    async function resetModule() {
        setBusy(true);
        try {
            const values = await request<
                Record<Section, Snapshot<Sections[Section]>>
            >(`/guilds/${guild}/modules/moderation/reset`, 'POST');
            setSnapshot(values[section]);
            setDraft(values[section].data);
            setReset(false);
            setSuccess(true);
            await reload();
        } catch (e) {
            setError((e as Error).message);
            setReset(false);
        } finally {
            setBusy(false);
        }
    }
    if (!draft)
        return (
            <State
                title={
                    error
                        ? 'Configuration unavailable'
                        : 'Retrieving your settings'
                }
                detail={error || undefined}
                busy={!error}
                retry={error ? () => void load() : undefined}
            />
        );
    function change(value: Sections[Section]) {
        setDraft(value);
        setSuccess(false);
    }
    let form: ReactNode;
    if (section === 'general') {
        const value = draft as Sections['general'];
        form = (
            <>
                <SectionTitle
                    title="General"
                    description="Control the module without losing its configuration."
                />
                <Toggle
                    label="Enable Moderation"
                    description="Allow your team to run enabled moderation commands."
                    value={value.enabled}
                    onChange={(enabled) => change({ ...value, enabled })}
                />
                <div className="explanation">
                    <Shield size={22} />
                    <p>
                        Disabling Moderation prevents new operations. Committed
                        work, including temporary-ban expiration, continues as
                        scheduled.
                    </p>
                </div>
                <div className="danger-zone">
                    <div>
                        <h3>Reset Moderation</h3>
                        <p>
                            Restore command, role, audit and Message Logging
                            defaults. Temporary bans are preserved.
                        </p>
                    </div>
                    <button
                        className="danger-outline"
                        onClick={() => setReset(true)}
                    >
                        <RotateCcw size={16} />
                        Reset to defaults
                    </button>
                </div>
            </>
        );
    } else if (section === 'commands') {
        const value = draft as Sections['commands'];
        form = (
            <>
                <SectionTitle
                    title="Commands"
                    description="Choose which operations your team can use in Discord."
                />
                {value.commands.map((command, index) => (
                    <Toggle
                        key={command.name}
                        label={`/${command.name}`}
                        description={`${commandDescriptions[command.name]} · ${permissions[command.name]} · ${overview.access.data.commands.find((x) => x.name === command.name)?.mode === 'custom' ? 'Custom roles' : 'Inherits module roles'}`}
                        value={command.enabled}
                        onChange={(enabled) =>
                            change({
                                ...value,
                                commands: value.commands.map((x, i) =>
                                    i === index ? { ...x, enabled } : x,
                                ),
                            })
                        }
                    />
                ))}
            </>
        );
    } else if (section === 'access') {
        const value = draft as Sections['access'];
        form = (
            <>
                <SectionTitle
                    title="Access controls"
                    description="Choose the roles trusted to use Moderation commands."
                />
                <Callout>
                    Custom command roles replace module roles. Empty roles deny
                    access. Server owners and Administrators receive no
                    operational bypass.
                </Callout>
                <Selector
                    label="Default allowed roles"
                    options={entities}
                    value={value.roles}
                    multiple
                    onChange={(roles) => change({ ...value, roles })}
                />
                <h3 className="subheading">Command overrides</h3>
                {value.commands.map((command, index) => (
                    <details className="event-group" key={command.name}>
                        <summary>
                            /{command.name}
                            <span>
                                {command.mode === 'inherit'
                                    ? 'Inherit module roles'
                                    : 'Custom roles'}
                            </span>
                        </summary>
                        <label className="field-label">
                            Access mode
                            <select
                                value={command.mode}
                                onChange={(e) =>
                                    change({
                                        ...value,
                                        commands: value.commands.map((x, i) =>
                                            i === index
                                                ? {
                                                      ...x,
                                                      mode: e.target.value as
                                                          'inherit' | 'custom',
                                                  }
                                                : x,
                                        ),
                                    })
                                }
                            >
                                <option value="inherit">
                                    Inherit module roles
                                </option>
                                <option value="custom">Custom roles</option>
                            </select>
                        </label>
                        {command.mode === 'custom' && (
                            <Selector
                                label={`Roles for /${command.name}`}
                                options={entities}
                                value={command.roles}
                                multiple
                                onChange={(roles) =>
                                    change({
                                        ...value,
                                        commands: value.commands.map((x, i) =>
                                            i === index ? { ...x, roles } : x,
                                        ),
                                    })
                                }
                            />
                        )}
                    </details>
                ))}
            </>
        );
    } else if (section === 'logging') {
        const value = draft as Sections['logging'];
        const channels = entities.filter((x) => x.type === 0 || x.type === 5);
        form = (
            <>
                <SectionTitle
                    title="Audit & Logging"
                    description="The right events, delivered to the right Discord channels."
                />
                <Diagnostics overview={overview} />
                <Toggle
                    label="Enable audit logging"
                    description="Controls all audit and Message Logging delivery."
                    value={value.enabled}
                    onChange={(enabled) => change({ ...value, enabled })}
                />
                <Selector
                    label="Default destination"
                    options={channels}
                    value={value.default_channel ? [value.default_channel] : []}
                    onChange={(ids) =>
                        change({ ...value, default_channel: ids[0] ?? null })
                    }
                />
                <p className="muted">
                    A usable default is required, even when overrides are
                    configured. Destinations require View Channel, Send Messages
                    and Embed Links.
                </p>
                <h3 className="subheading">Event categories</h3>
                {value.categories.map((category, index) => (
                    <details className="event-group" key={category.category}>
                        <summary>
                            {humanize(category.category)}
                            <span>
                                {
                                    value.events.filter(
                                        (x) =>
                                            overview.events.find(
                                                (e) => e.kind === x.kind,
                                            )?.category === category.category,
                                    ).length
                                }{' '}
                                events
                            </span>
                        </summary>
                        <Selector
                            label={`${humanize(category.category)} destination override`}
                            options={channels}
                            value={category.channel ? [category.channel] : []}
                            onChange={(ids) =>
                                change({
                                    ...value,
                                    categories: value.categories.map((x, i) =>
                                        i === index
                                            ? { ...x, channel: ids[0] ?? null }
                                            : x,
                                    ),
                                })
                            }
                        />
                        {value.events
                            .filter(
                                (x) =>
                                    overview.events.find(
                                        (e) => e.kind === x.kind,
                                    )?.category === category.category,
                            )
                            .map((event) => (
                                <EventControls
                                    key={event.kind}
                                    event={event}
                                    channels={channels}
                                    update={(updated) =>
                                        change({
                                            ...value,
                                            events: value.events.map((x) =>
                                                x.kind === updated.kind
                                                    ? updated
                                                    : x,
                                            ),
                                        })
                                    }
                                />
                            ))}
                        {category.category === 'message_logging' && (
                            <p>
                                Configure the three content events on the
                                Message Logging tab.
                            </p>
                        )}
                    </details>
                ))}
            </>
        );
    } else {
        const value = draft as Sections['message-logging'];
        form = (
            <>
                <SectionTitle
                    title="Message Logging"
                    description="Configure optional message content delivery to Discord."
                />
                {overview.diagnostics.capabilities.includes(
                    'message_content_unavailable',
                ) && (
                    <Callout>
                        Message Logging can be configured, but cannot operate
                        until Message Content access is enabled for Requiem.
                        Your desired settings remain saved.
                    </Callout>
                )}
                {value.events.map((event) => (
                    <EventControls
                        key={event.kind}
                        event={event}
                        channels={entities.filter(
                            (x) => x.type === 0 || x.type === 5,
                        )}
                        update={(updated) =>
                            change({
                                ...value,
                                events: value.events.map((x) =>
                                    x.kind === updated.kind ? updated : x,
                                ),
                            })
                        }
                    />
                ))}
                <h3 className="subheading">Authors & scope</h3>
                <Toggle
                    label="Include bots"
                    value={value.include_bots}
                    onChange={(include_bots) =>
                        change({ ...value, include_bots })
                    }
                />
                <Toggle
                    label="Include webhooks"
                    value={value.include_webhooks}
                    onChange={(include_webhooks) =>
                        change({ ...value, include_webhooks })
                    }
                />
                <label className="field-label">
                    Scope mode
                    <select
                        value={value.scope}
                        onChange={(e) =>
                            change({
                                ...value,
                                scope: e.target
                                    .value as Sections['message-logging']['scope'],
                            })
                        }
                    >
                        <option value="all_except_exclusions">
                            All channels except exclusions
                        </option>
                        <option value="selected_channels_only">
                            Selected channels only
                        </option>
                    </select>
                </label>
                <Selector
                    label={
                        value.scope === 'all_except_exclusions'
                            ? 'Excluded channels'
                            : 'Selected channels'
                    }
                    options={entities}
                    multiple
                    value={value.channels}
                    onChange={(channels) => change({ ...value, channels })}
                />
                <div className="explanation">
                    <Workflow size={22} />
                    <p>
                        Threads inherit their parent channel's scope. Requiem
                        logging destinations and Requiem's own messages are
                        always excluded to prevent loops.
                    </p>
                </div>
            </>
        );
    }
    return (
        <>
            <UnsavedGuard dirty={dirty} />
            <section className="settings-panel glass">
                <fieldset disabled={busy} className="form-fields">
                    {form}
                </fieldset>
            </section>
            {error && (
                <Callout>
                    {conflict ? locale.copy.conflict : error}
                    {conflict && (
                        <button onClick={() => void load()}>
                            Reload latest settings
                        </button>
                    )}
                </Callout>
            )}
            {success && <Callout tone="success">{locale.copy.saved}</Callout>}
            <div className={`save-bar glass ${dirty ? 'dirty' : ''}`}>
                <span>
                    {dirty ? 'You have unsaved changes' : 'All changes saved'}
                </span>
                <div className="actions">
                    <button
                        disabled={!dirty || busy}
                        onClick={() => {
                            setDraft(snapshot!.data);
                            setError('');
                            setConflict(false);
                        }}
                    >
                        Discard
                    </button>
                    <button
                        className="primary"
                        disabled={!dirty || busy || conflict}
                        onClick={() => void save()}
                    >
                        {busy ? 'Saving…' : 'Save changes'}
                    </button>
                </div>
            </div>
            {reset && (
                <Dialog
                    title="Reset Moderation?"
                    danger
                    busy={busy}
                    actionLabel="Reset Moderation"
                    onClose={() => setReset(false)}
                    action={() => void resetModule()}
                >
                    <p>
                        All Moderation settings will return to their server
                        defaults. This includes access roles, commands, audit
                        logging and Message Logging.
                    </p>
                    <p>
                        Existing temporary bans and their expiration schedules
                        remain intact.
                    </p>
                </Dialog>
            )}
        </>
    );
}
function SectionTitle({
    title,
    description,
}: {
    title: string;
    description: string;
}) {
    return (
        <div className="section-title">
            <h2>{title}</h2>
            <p>{description}</p>
        </div>
    );
}
function EventControls({
    event,
    channels,
    update,
}: {
    event: EventSetting;
    channels: Entity[];
    update: (value: EventSetting) => void;
}) {
    return (
        <div className="event-controls">
            <Toggle
                label={humanize(event.kind)}
                value={event.enabled}
                onChange={(enabled) => update({ ...event, enabled })}
            />
            <details className="override">
                <summary>Destination override</summary>
                <Selector
                    label={`${humanize(event.kind)} destination`}
                    options={channels}
                    value={event.channel ? [event.channel] : []}
                    onChange={(ids) =>
                        update({ ...event, channel: ids[0] ?? null })
                    }
                />
            </details>
        </div>
    );
}
export function Diagnostics({ overview }: { overview: Overview }) {
    return (
        <div className="diagnostics">
            <span className="badge">
                Logging: {humanize(overview.diagnostics.status)}
            </span>
            {overview.diagnostics.destinations
                .filter(([, status]) => status !== 'ready')
                .map(([id, status]) => (
                    <Callout key={id}>
                        Destination {id}: {humanize(status)}
                    </Callout>
                ))}
            {overview.diagnostics.capabilities.map((status) => (
                <Callout key={status}>
                    {humanize(status)}. Related observation may be unavailable.
                </Callout>
            ))}
        </div>
    );
}
const commandDescriptions: Record<string, string> = {
    warn: 'Send a formal warning',
    timeout: 'Temporarily restrict a member',
    untimeout: 'Remove a timeout',
    kick: 'Remove a member',
    ban: 'Ban a user permanently or temporarily',
    unban: 'Lift a ban',
    purge: 'Remove eligible recent messages',
};
const permissions: Record<string, string> = {
    warn: 'Moderate Members',
    timeout: 'Moderate Members',
    untimeout: 'Moderate Members',
    kick: 'Kick Members',
    ban: 'Ban Members',
    unban: 'Ban Members',
    purge: 'Manage Messages and Read Message History',
};
