import { AccountDeletion } from "@/components/account_deletion";
import { DisplayNameForm } from "@/components/display_name_form";
import { SaveStatus } from "@/components/save_status";
import { extensions } from "@/extensions";
import { useAuthStore } from "@/stores/auth_store";

/** One quiet line: save state, then the account, with details on demand. */
export default function SessionStatus() {
  const Hosted = extensions.session?.SessionStatus;
  return Hosted ? <Hosted /> : <LocalSessionStatus />;
}

function LocalSessionStatus() {
  const user = useAuthStore((s) => s.user);
  if (!user) return null;
  return (
    <div className="session-status">
      <SaveStatus />
      <details className="session-details">
        <summary>Account</summary>
        <div className="session-details-body">
          {!user.is_anonymous && <DisplayNameForm key={user.id} user={user} />}
          <nav aria-label="Help">
            <a href="/help">Help</a>
          </nav>
          <div className="session-danger-zone">
            <AccountDeletion />
          </div>
        </div>
      </details>
    </div>
  );
}
