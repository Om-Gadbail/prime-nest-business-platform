/**
 * Verification-host Vite config (HOST-ONLY — production modules untouched).
 *
 * Injects VITE_* env at serve time, which is exactly what the production
 * Nest site's Vite build does for `import.meta.env`. The drop-in modules
 * (`../backend.ts`, `../forms.ts`, `../attribution.ts`) stay byte-identical
 * on disk to what ships to the real Nest website.
 */
import { defineConfig } from "file:///C:/Users/ossag/OneDrive/Desktop/prime-nest-business-platform/apps/staff-dashboard/node_modules/vite/dist/node/index.js";

const NEST_VERIFY_ENV = JSON.stringify({
  VITE_API_BASE_URL: "http://localhost:8000",
  VITE_BUSINESS_SLUG: "nest",
});

export default defineConfig({
  plugins: [
    {
      name: "nest-verify-env",
      transform(code, id) {
        if (id.endsWith("integrations/nest-website/backend.ts")) {
          return code.replace("return meta.env;", `return (${NEST_VERIFY_ENV});`);
        }
        return null;
      },
    },
  ],
});
