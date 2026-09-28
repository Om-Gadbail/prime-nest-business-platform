/**
 * Verification-host wiring for the Nest drop-in package.
 *
 * This file contains NO business logic of its own: it imports the EXACT
 * production modules (`../backend.ts`, `../forms.ts`) and wires them to a
 * minimal DOM host so a real Chromium can exercise the production request
 * path (config -> POST /api/v1/public/nest/leads -> success/error states).
 */
import { getPublicConfig } from "../backend.js";
import { saveNestEnquiry } from "../forms.js";

const form = document.getElementById("enquiry-form") as HTMLFormElement;
const result = document.getElementById("result") as HTMLDivElement;
const configStatus = document.getElementById("config-status") as HTMLParagraphElement;

function setResult(state: string, message: string): void {
  result.dataset.state = state;
  result.textContent = message;
}

async function boot(): Promise<void> {
  try {
    const config = await getPublicConfig();
    configStatus.textContent = `Config: ${config.slug} lead_capture=${String(
      config.leadCaptureEnabled,
    )} booking=${String(config.bookingEnabled)}`;
    configStatus.dataset.loaded = "true";
  } catch (err) {
    configStatus.textContent = `Config unavailable: ${
      err instanceof Error ? err.message : String(err)
    }`;
    configStatus.dataset.loaded = "false";
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const data = new FormData(form);
  const run = async (): Promise<void> => {
    setResult("pending", "Sending…");
    const outcome = await saveNestEnquiry({
      name: String(data.get("name") ?? ""),
      phone: String(data.get("phone") ?? ""),
      interest: ((): "Seat Inquiry" | "Membership Inquiry" | "Contact" | "Other" => {
        const raw = String(data.get("interest") ?? "Seat Inquiry");
        return raw === "Membership Inquiry" || raw === "Contact" || raw === "Other"
          ? raw
          : "Seat Inquiry";
      })(),
      message: String(data.get("message") ?? ""),
      source: "website:seat-inquiry-form",
      honeypot: String(data.get("website_url") ?? ""),
    });
    if (outcome.ok) {
      setResult("success", outcome.message);
      (window as unknown as { __nestLastRequestId?: string }).__nestLastRequestId =
        outcome.backendRequestId ?? "";
    } else {
      setResult("error", outcome.message);
    }
  };
  void run();
});

void boot();
