import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { SessionProvider } from './lib/auth';
import { createQueryClient } from './lib/query';
import { ToastProvider } from './components/ui/Toast';
import { Shell } from './components/layout/Shell';
import { RequireAuth } from './features/auth/guards';
import { LoginPage } from './features/auth/LoginPage';
import { OverviewPage } from './features/overview/OverviewPage';
import { LeadDetailPage } from './features/leads/LeadDetailPage';
import { LeadsPage } from './features/leads/LeadsPage';
import { BookingDetailPage, BookingsPage } from './features/bookings/BookingsPages';
import { ContactDetailPage, ContactsPage, CustomerDetailPage, CustomersPage } from './features/crm/CrmPages';
import { TaskDetailPage, TasksPage } from './features/tasks/TasksPages';
import { NotificationsPage } from './features/notifications/NotificationsPage';
import { ActivityPage } from './features/activity/ActivityPage';
import { SettingsPage } from './features/settings/SettingsPage';
import { OwnerPage } from './features/owner/OwnerPage';
import { MemberDetailPage } from './features/members/MemberDetailPage';
import { MembersPage } from './features/members/MembersPage';
import { MembershipsPage } from './features/memberships/MembershipsPage';
import { PlansPage } from './features/memberships/PlansPage';
import { RenewalsPage } from './features/memberships/RenewalsPage';
import { PaymentsPage } from './features/payments/PaymentsPage';
import { AttendancePage } from './features/attendance/AttendancePage';
import { SeatsPage } from './features/seats/SeatsPage';
import { ApprovalsPage } from './features/approvals/ApprovalsPage';
import { AutomationPage } from './features/automation/AutomationPage';
import { CommsPage } from './features/communications/CommsPage';
import { AssistantPage } from './features/assistant/AssistantPage';
import { GrowthPage } from './features/growth/GrowthPage';
import { AnalyticsPage } from './features/analytics/AnalyticsPage';

const queryClient = createQueryClient();

/**
 * Shared staff dashboard router. Prime, Nest, and Owner share the same
 * routes; business identity + permissions come from the backend session,
 * so navigation, data, and branding always reflect the active context.
 */
export function App(): JSX.Element {
  return (
    <QueryClientProvider client={queryClient}>
      <SessionProvider>
        <ToastProvider>
          <BrowserRouter>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route
                element={
                  <RequireAuth>
                    <Shell />
                  </RequireAuth>
                }
              >
                <Route index element={<OverviewPage />} />
                <Route path="owner" element={<OwnerPage />} />
                <Route path="leads" element={<LeadsPage />} />
                <Route path="leads/:id" element={<LeadDetailPage />} />
                <Route path="bookings" element={<BookingsPage />} />
                <Route path="bookings/:id" element={<BookingDetailPage />} />
                <Route path="contacts" element={<ContactsPage />} />
                <Route path="contacts/:id" element={<ContactDetailPage />} />
                <Route path="customers" element={<CustomersPage />} />
                <Route path="customers/:id" element={<CustomerDetailPage />} />
                <Route path="members" element={<MembersPage />} />
                <Route path="members/:id" element={<MemberDetailPage />} />
                <Route path="memberships" element={<MembershipsPage />} />
                <Route path="plans" element={<PlansPage />} />
                <Route path="renewals" element={<RenewalsPage />} />
                <Route path="payments" element={<PaymentsPage />} />
                <Route path="attendance" element={<AttendancePage />} />
                <Route path="seats" element={<SeatsPage />} />
                <Route path="approvals" element={<ApprovalsPage />} />
                <Route path="automation" element={<AutomationPage />} />
                <Route path="communications" element={<CommsPage />} />
                <Route path="assistant" element={<AssistantPage />} />
                <Route path="growth" element={<GrowthPage />} />
                <Route path="analytics" element={<AnalyticsPage />} />
                <Route path="tasks" element={<TasksPage />} />
                <Route path="tasks/:id" element={<TaskDetailPage />} />
                <Route path="notifications" element={<NotificationsPage />} />
                <Route path="activity" element={<ActivityPage />} />
                <Route path="settings" element={<SettingsPage />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Route>
            </Routes>
          </BrowserRouter>
        </ToastProvider>
      </SessionProvider>
    </QueryClientProvider>
  );
}
