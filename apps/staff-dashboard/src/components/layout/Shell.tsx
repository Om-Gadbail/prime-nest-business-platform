import { useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import {
  Activity,
  Armchair,
  BadgeCheck,
  Bell,
  BookOpenCheck,
  Bot,
  CalendarCheck,
  CalendarClock,
  CheckSquare,
  ChevronDown,
  Contact,
  CreditCard,
  Crown,
  Home,
  LineChart,
  LogOut,
  Megaphone,
  Menu,
  MessagesSquare,
  RefreshCcw,
  Settings,
  ShieldCheck,
  UserCheck,
  Users,
  X,
  Zap,
} from 'lucide-react';
import { useSession } from '../../lib/auth';
import { displayName } from '../../config/business';
import { useUnreadCount } from '../../features/notifications/hooks';

/** Shared dashboard shell: dark sidebar (desktop), bottom nav (mobile). */

interface NavItem {
  to: string;
  label: string;
  icon: typeof Home;
  permission: string;
  end?: boolean;
}

const NAV: NavItem[] = [
  { to: '/', label: 'Overview', icon: Home, permission: 'dashboard.read', end: true },
  { to: '/owner', label: 'Owner', icon: Crown, permission: 'owner.dashboard.read' },
  { to: '/leads', label: 'Leads', icon: Users, permission: 'leads.read' },
  { to: '/bookings', label: 'Bookings', icon: CalendarClock, permission: 'bookings.read' },
  { to: '/contacts', label: 'Contacts', icon: Contact, permission: 'contacts.read' },
  { to: '/customers', label: 'Customers', icon: BookOpenCheck, permission: 'customers.read' },
  { to: '/members', label: 'Members', icon: UserCheck, permission: 'members.read' },
  { to: '/memberships', label: 'Memberships', icon: BadgeCheck, permission: 'memberships.read' },
  { to: '/plans', label: 'Plans', icon: BookOpenCheck, permission: 'membership_plans.read' },
  { to: '/payments', label: 'Payments', icon: CreditCard, permission: 'payments.read' },
  { to: '/attendance', label: 'Attendance', icon: CalendarCheck, permission: 'attendance.read' },
  { to: '/renewals', label: 'Renewals', icon: RefreshCcw, permission: 'renewals.read' },
  { to: '/seats', label: 'Seats', icon: Armchair, permission: 'seats.read' },
  { to: '/approvals', label: 'Approvals', icon: ShieldCheck, permission: 'approvals.read' },
  { to: '/automation', label: 'Automation', icon: Zap, permission: 'automation.read' },
  { to: '/communications', label: 'Comms', icon: MessagesSquare, permission: 'communications.read' },
  { to: '/assistant', label: 'AI Assistant', icon: Bot, permission: 'ai.assist' },
  { to: '/growth', label: 'Growth', icon: Megaphone, permission: 'growth.read' },
  { to: '/analytics', label: 'Intelligence', icon: LineChart, permission: 'analytics.read' },
  { to: '/tasks', label: 'Tasks', icon: CheckSquare, permission: 'tasks.read' },
  { to: '/notifications', label: 'Notifications', icon: Bell, permission: 'notifications.read' },
  { to: '/activity', label: 'Activity', icon: Activity, permission: 'audit.read' },
  { to: '/settings', label: 'Settings', icon: Settings, permission: 'settings.read' },
];

/** Bottom-nav priority: the five most-used modules first (mobile). */
const MOBILE_PRIORITY = ['/', '/leads', '/bookings', '/tasks', '/notifications'];

const TITLES: Array<[RegExp, string]> = [
  [/^\/$/, 'Overview'],
  [/^\/owner(\/|$)/, 'Owner'],
  [/^\/leads(\/|$)/, 'Leads'],
  [/^\/bookings(\/|$)/, 'Bookings'],
  [/^\/contacts(\/|$)/, 'Contacts'],
  [/^\/customers(\/|$)/, 'Customers'],
  [/^\/members(\/|$)/, 'Members'],
  [/^\/memberships(\/|$)/, 'Memberships'],
  [/^\/plans(\/|$)/, 'Plans'],
  [/^\/payments(\/|$)/, 'Payments'],
  [/^\/attendance(\/|$)/, 'Attendance'],
  [/^\/renewals(\/|$)/, 'Renewals'],
  [/^\/seats(\/|$)/, 'Seats'],
  [/^\/approvals(\/|$)/, 'Approvals'],
  [/^\/automation(\/|$)/, 'Automation'],
  [/^\/communications(\/|$)/, 'Communications'],
  [/^\/assistant(\/|$)/, 'AI Assistant'],
  [/^\/growth(\/|$)/, 'Growth'],
  [/^\/analytics(\/|$)/, 'Intelligence'],
  [/^\/tasks(\/|$)/, 'Tasks'],
  [/^\/notifications(\/|$)/, 'Notifications'],
  [/^\/activity(\/|$)/, 'Activity'],
  [/^\/settings(\/|$)/, 'Settings'],
];

export function Shell(): JSX.Element {
  const { me, preset, can, logout, businesses, switchBusiness } = useSession();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [switcherOpen, setSwitcherOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const businessId = me?.business?.id ?? '';
  const { data: unread } = useUnreadCount(businessId);
  const visible = NAV.filter((item) => can(item.permission));
  const rank = (to: string): number => {
    const i = MOBILE_PRIORITY.indexOf(to);
    return i === -1 ? MOBILE_PRIORITY.length : i;
  };
  const mobileNav = [...visible]
    .sort((a, b) => rank(a.to) - rank(b.to))
    .slice(0, 5);
  const name = displayName(me?.business?.name, me?.business?.slug ?? preset.slug);
  const current = TITLES.find(([re]) => re.test(location.pathname))?.[1] ?? 'Overview';

  const onLogout = async (): Promise<void> => {
    await logout();
    navigate('/login', { replace: true });
  };

  const sidebar = (
    <div className="flex h-full flex-col bg-slate-950 text-slate-200">
      <div className="flex items-center gap-3 px-5 pb-5 pt-6">
        <span
          aria-hidden
          className="flex h-10 w-10 items-center justify-center rounded-xl text-sm font-black text-white"
          style={{ backgroundColor: preset.accent }}
        >
          {preset.initials}
        </span>
        <div className="min-w-0">
          <p className="truncate text-sm font-bold text-white">{name}</p>
          <p className="text-xs text-slate-400">{me?.membership?.role ?? ''} · {preset.tagline}</p>
        </div>
      </div>
      <nav aria-label="Primary" className="flex-1 space-y-1 overflow-y-auto px-3">
        {visible.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={() => setMobileOpen(false)}
            className={({ isActive }) =>
              `flex min-h-[44px] items-center gap-3 rounded-xl px-3 text-sm font-medium transition ${
                isActive ? 'bg-white/10 text-white' : 'text-slate-300 hover:bg-white/5 hover:text-white'
              }`
            }
          >
            <item.icon className="h-5 w-5 shrink-0" aria-hidden />
            {item.label}
            {item.to === '/notifications' && (unread ?? 0) > 0 ? (
              <span className="ml-auto rounded-full bg-rose-500 px-2 py-0.5 text-[11px] font-bold text-white">
                {unread}
              </span>
            ) : null}
          </NavLink>
        ))}
      </nav>
      <div className="border-t border-white/10 p-4">
        <p className="truncate px-1 text-xs text-slate-400">{me?.user.email}</p>
        <button
          type="button"
          onClick={onLogout}
          className="mt-2 flex min-h-[44px] w-full cursor-pointer items-center gap-3 rounded-xl px-3 text-sm font-medium text-slate-300 hover:bg-white/5 hover:text-white"
        >
          <LogOut className="h-5 w-5" aria-hidden /> Sign out
        </button>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen bg-slate-100">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 hidden w-64 lg:block" aria-hidden={false}>
        {sidebar}
      </aside>
      {/* Mobile drawer */}
      {mobileOpen ? (
        <div className="fixed inset-0 z-50 lg:hidden" role="presentation" onClick={() => setMobileOpen(false)}>
          <aside className="h-full w-72 max-w-[85vw]" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-end bg-slate-950 px-3 pt-3">
              <button
                type="button"
                aria-label="Close navigation"
                onClick={() => setMobileOpen(false)}
                className="flex h-10 w-10 cursor-pointer items-center justify-center rounded-lg text-slate-300 hover:bg-white/10"
              >
                <X className="h-5 w-5" aria-hidden />
              </button>
            </div>
            <div className="h-[calc(100%-52px)]">{sidebar}</div>
          </aside>
        </div>
      ) : null}

      <div className="lg:pl-64">
        <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/90 backdrop-blur">
          <div className="flex min-h-[60px] items-center gap-2 px-4 sm:px-6">
            <button
              type="button"
              aria-label="Open navigation"
              onClick={() => setMobileOpen(true)}
              className="flex h-10 w-10 cursor-pointer items-center justify-center rounded-lg text-slate-600 hover:bg-slate-100 lg:hidden"
            >
              <Menu className="h-5 w-5" aria-hidden />
            </button>
            <nav aria-label="Breadcrumb" className="min-w-0">
              <p className="truncate text-sm font-semibold text-slate-900">{current}</p>
              <p className="truncate text-xs text-slate-500">{name}</p>
            </nav>
            <div className="ml-auto flex items-center gap-2">
              {businesses.length > 1 ? (
                <div className="relative">
                  <button
                    type="button"
                    onClick={() => setSwitcherOpen((v) => !v)}
                    aria-haspopup="listbox"
                    aria-expanded={switcherOpen}
                    className="flex h-10 cursor-pointer items-center gap-1.5 rounded-xl px-3 text-sm font-semibold text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50"
                  >
                    {preset.shortName} <ChevronDown className="h-4 w-4" aria-hidden />
                  </button>
                  {switcherOpen ? (
                    <ul role="listbox" aria-label="Switch business" className="absolute right-0 z-40 mt-2 w-56 rounded-xl bg-white p-1.5 shadow-lg ring-1 ring-slate-200">
                      {businesses.map((b) => (
                        <li key={b.business.id}>
                          <button
                            type="button"
                            role="option"
                            aria-selected={b.business.id === businessId}
                            onClick={async () => {
                              setSwitcherOpen(false);
                              if (b.business.id !== businessId) {
                                await switchBusiness(b.business.slug);
                                navigate('/', { replace: true });
                              }
                            }}
                            className="flex min-h-[44px] w-full cursor-pointer items-center justify-between rounded-lg px-3 text-left text-sm hover:bg-slate-100"
                          >
                            <span>
                              <span className="block font-semibold text-slate-800">{b.business.name}</span>
                              <span className="block text-xs text-slate-500">{b.role}</span>
                            </span>
                            {b.business.id === businessId ? <span aria-hidden className="text-emerald-600">●</span> : null}
                          </button>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              ) : (
                <span className="hidden rounded-full px-3 py-1.5 text-xs font-bold text-white sm:inline-block" style={{ backgroundColor: preset.accent }}>
                  {preset.shortName}
                </span>
              )}
            </div>
          </div>
        </header>

        <main className="mx-auto w-full max-w-6xl px-4 pb-24 pt-5 sm:px-6 lg:pb-10">
          <Outlet />
        </main>

        {/* Mobile bottom navigation */}
        <nav aria-label="Primary mobile" className="fixed inset-x-0 bottom-0 z-30 border-t border-slate-200 bg-white lg:hidden">
          <div className="grid grid-cols-5">
            {mobileNav.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `flex min-h-[56px] flex-col items-center justify-center gap-1 text-[11px] font-semibold ${
                    isActive ? 'text-slate-900' : 'text-slate-500'
                  }`
                }
              >
                <item.icon className="h-5 w-5" aria-hidden />
                {item.label}
              </NavLink>
            ))}
          </div>
        </nav>
      </div>
    </div>
  );
}
